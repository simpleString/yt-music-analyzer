import difflib
import json
import re
import threading
import time
from datetime import datetime

import httpx
from langdetect import DetectorFactory, detect
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import AudioFeatures, Lyrics, Track
from app.services import jobs
from app.services import errors as errors_svc
from app.services.topics import extract_topics

LRCLIB_SEARCH = "https://lrclib.net/api/search"
MIN_MATCH_RATIO = 0.6
# fuzzy-match ratio high enough to declare "the track has words"
CONFIRM_RATIO = 0.8

DetectorFactory.seed = 0

# langdetect splits Chinese into zh-cn/zh-tw — store one code
_LANG_ALIASES = {"zh-cn": "zh", "zh-tw": "zh"}

TITLE_JUNK_RE = re.compile(
    r"[([](official|lyrics?|lyric|audio|video|visualizer|remaster\w*|hd|hq|4k|mv"
    r"|explicit|clean|full version|version|premiere|премьера|официальн\w*"
    r"|live|session|studio|parody|пароди\w*|cover|кавер|remix|ремикс|radio edit"
    r"|outro|intro|bonus|re-?upload|reupload|full|tv anime|anime|amv"
    r"|[^)\]]*20\d{2}[^)\]]*)[^)\]]*[)\]]",
    re.I,
)
# "| Live From ..." — tail after a vertical bar with live markers
PIPE_TAIL_RE = re.compile(
    r"\s*[\|/]\s*(live|session|studio|from|official|version|edit|remix).*$", re.I
)
# leading track number: "23. ", "6. ", "07 - ", "Track 3"
TRACK_NUM_RE = re.compile(r"^\s*(track\s*)?\d{1,2}[\s.\-_]+\s*", re.I)
# anime/fandom brackets: 【...】〖...〗｢...｣ and the tail after " × " (with spaces,
# so words with a latin x like "Oxxxymiron" are not cut)
CJK_BRACKETS_RE = re.compile(
    r"[【〖｢\[][^】〗｣\]]{0,50}[】〗｣\]]|\s+[×x]\s+.*$"
)
FEAT_RE = re.compile(r"\s*[([]?\s*(feat\.?|ft\.?|featuring|при уч\.)\s.*$", re.I)

RU_POS = (
    "любл люблю любовь любим мила милая милый нежн нежность счаст счасть "
    "радост свет солнц тёпл тёплы теплые добр друз друг весен цветок небо "
    "мечт вдохнов свобод улыб лето dance"
)
RU_NEG = (
    "ненавижу боль больно бо боюсь страх страш плак плач слез слёз груст "
    "печал тоск одинок пуст тьм холод зим смерть умер убей прощай разрыв "
    "разбит жесток война кровь раны рыда"
)
EN_POS = (
    "love lovely beautiful happy sunshine light warm sweet dream hope free "
    "freedom smile dancing summer friend forever heaven shine bright kiss "
    "hold heart soul together alive"
)
EN_NEG = (
    "hate pain hurt cry crying tears sad lonely alone dark cold death dead "
    "die dying broken break goodbye leaving gone war blood knife fear afraid "
    "scared lost empty miss missing"
)


def _clean_title(title: str) -> tuple[str, str]:
    """«Artist - Song (Official Video)» → (artist_guess, song)."""
    t = TITLE_JUNK_RE.sub("", title or "")
    t = CJK_BRACKETS_RE.sub("", t)
    t = PIPE_TAIL_RE.sub("", t)
    t = " ".join(t.split()).strip(" -|")
    artist = ""
    song = t
    if " - " in t:
        parts = t.split(" - ", 1)
        artist, song = parts[0].strip(), parts[1].strip()
    # feat tails and leading numbers — after the artist/song split
    song = FEAT_RE.sub("", song).strip()
    song = TRACK_NUM_RE.sub("", song).strip()
    artist = FEAT_RE.sub("", artist).strip()
    # "Кожура/Я всё решу" — double title, take the first part
    if "/" in song and len(song.split("/")) == 2:
        first = song.split("/", 1)[0].strip()
        if 3 <= len(first) <= 60:
            song = first
    return artist, song


def _artist_from_channel(channel: str) -> str:
    ch = (channel or "").strip()
    if ch.lower().endswith(" - topic"):
        ch = ch[: -len(" - topic")]
    if ch.upper().endswith("VEVO") and len(ch) > 4:
        ch = ch[:-4]
    return ch.strip()


def detect_language(text: str) -> str:
    """ISO 639-1 language code of the text ('' if unsure)."""
    t = (text or "").strip()
    if not t:
        return ""
    try:
        code = detect(t)
    except Exception:
        return ""
    return _LANG_ALIASES.get(code, code)


def sentiment_score(text: str) -> float:
    t = (text or "").lower()
    if not t:
        return 0.0

    def count(stems: tuple) -> int:
        return sum(t.count(s) for s in stems)

    if detect_language(t) == "ru":
        pos, neg = count(RU_POS.split()), count(RU_NEG.split())
    else:
        pos, neg = count(EN_POS.split()), count(EN_NEG.split())
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 2)


_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = _last_call + 1.05 - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _norm(s: str) -> str:
    """Lowercase and strip punctuation, keeping letters of any alphabet."""
    return re.sub(r"[^\w\s]+", "", (s or "").lower()).strip()


def _lrclib_search(
    song: str, artist: str, client: httpx.Client
) -> list[dict]:
    _throttle()
    try:
        resp = client.get(
            LRCLIB_SEARCH,
            params={"track_name": song[:120], "artist_name": artist[:120]},
        )
        resp.raise_for_status()
        return resp.json()
    except ValueError:
        return []
    # httpx.HTTPError propagates: a network outage must not be mistaken
    # for "lyrics not found" (misses get cached, network errors don't)


def _fetch_lyrics(track: Track, client: httpx.Client) -> tuple[Lyrics | None, float]:
    artist_guess, song = _clean_title(track.title)
    artist = _artist_from_channel(track.channel) or artist_guess
    if not song:
        return None, 0.0
    hits = _lrclib_search(song, artist, client)
    if not hits and artist and artist != artist_guess and artist_guess:
        # the channel may be inaccurate (label, live channel) — try the artist from the title
        hits = _lrclib_search(song, artist_guess, client)
    if not hits:
        # last resort: search by song title only
        _throttle()
        try:
            resp = client.get(LRCLIB_SEARCH, params={"track_name": song[:120]})
            resp.raise_for_status()
            hits = resp.json()
        except ValueError:
            hits = []
    if not hits:
        # final fallback: free-form query across all fields
        _throttle()
        try:
            resp = client.get(
                LRCLIB_SEARCH, params={"q": f"{artist} {song}"[:200]}
            )
            resp.raise_for_status()
            hits = resp.json()
        except ValueError:
            hits = []
    best, best_ratio = None, 0.0
    target = _norm(f"{artist} {song}")
    for hit in hits[:8]:
        candidate = _norm(f"{hit.get('artistName', '')} {hit.get('trackName', '')}")
        ratio = difflib.SequenceMatcher(None, target, candidate).ratio()
        if ratio > best_ratio:
            best, best_ratio = hit, ratio
    if best is None or best_ratio < MIN_MATCH_RATIO:
        # no artist in the target — title-only match
        target_song = _norm(song)
        for hit in hits[:8]:
            candidate = _norm(hit.get("trackName", ""))
            ratio = difflib.SequenceMatcher(None, target_song, candidate).ratio()
            if ratio > best_ratio:
                best, best_ratio = hit, ratio
    if best is None or best_ratio < MIN_MATCH_RATIO:
        return None, 0.0
    text = best.get("plainLyrics") or ""
    if not text:
        return None, 0.0
    language = detect_language(text)
    topics = extract_topics(text, language)
    row = Lyrics(
        track_id=track.video_id,
        text=text,
        synced=bool(best.get("syncedLyrics")),
        source="lrclib",
        language=language,
        sentiment=sentiment_score(text),
        topics=json.dumps(topics, ensure_ascii=False) if topics else "",
        fetched_at=datetime.utcnow(),
    )
    return row, best_ratio


def vocal_score(feat: AudioFeatures | None) -> float:
    """Combined vocal signal: the voice_instrumental head, plus the
    Jamendo "Voice" instrument score as an independent second opinion
    (the binary head sometimes underestimates vocals)."""
    if feat is None:
        return 0.0
    score = float(feat.vocal_ratio or 0.0)
    if feat.tags:
        try:
            data = json.loads(feat.tags)
            for inst in data.get("instruments", []):
                if str(inst.get("name", "")).lower() == "voice":
                    score = max(score, float(inst.get("score", 0.0)))
        except (ValueError, TypeError, KeyError):
            pass
    return score


def _set_has_vocals(session: Session, video_id: str, value: bool) -> None:
    feat = session.get(AudioFeatures, video_id)
    if feat is not None:
        feat.has_vocals = value
        session.add(feat)


def _whisper_verdict(track: Track, feat: AudioFeatures) -> bool | None:
    """Whisper spot-check for uncertain tracks. Returns the verdict or
    None (nothing checked: clearly vocal, audio missing, model failed).
    On a positive verdict the transcript is stored as fallback lyrics.
    """
    if vocal_score(feat) >= settings.lyrics_min_vocal:
        return None
    from app.services import vocals

    res = vocals.check_words(track.video_id, track.duration)
    if res is None:
        return None
    has_words = res["words"] >= settings.whisper_min_words
    with Session(engine) as session:
        _set_has_vocals(session, track.video_id, has_words)
        if has_words:
            text = res["text"]
            language = res["language"] or detect_language(text)
            topics = extract_topics(text, language)
            session.merge(
                Lyrics(
                    track_id=track.video_id,
                    text=text,
                    synced=False,
                    source="whisper",
                    language=language,
                    sentiment=sentiment_score(text),
                    topics=json.dumps(topics, ensure_ascii=False) if topics else "",
                    fetched_at=datetime.utcnow(),
                )
            )
        session.commit()
    return has_words


def run_lyrics(stop: threading.Event | None = None) -> None:
    try:
        if not jobs.start_job("lyrics"):
            return
        stop = stop if stop is not None else threading.Event()
        with Session(engine) as session:
            have = set(session.exec(select(Lyrics.track_id)).all())  # type: ignore[arg-type]
            stmt = (
                select(Track, AudioFeatures)
                .join(AudioFeatures, AudioFeatures.track_id == Track.video_id)
                .where(
                    Track.is_music == True,  # noqa: E712
                    Track.play_count >= settings.min_play_count,
                )
                .order_by(Track.play_count.desc())
            )
            pairs = [
                (t, f) for t, f in session.exec(stmt).all() if t.video_id not in have
            ]
        # most-played tracks first (the job is capped by lyrics_limit per
        # run); the vocal score is a tiebreak
        pairs.sort(key=lambda tf: (tf[0].play_count, vocal_score(tf[1])), reverse=True)
        candidates = pairs if settings.lyrics_limit <= 0 else pairs[: settings.lyrics_limit]

        total = len(candidates)
        jobs.progress(
            "lyrics", 0, total, f"to search: {total}" if total
            else "no tracks to search lyrics for",
        )

        found = 0
        confirmed = 0
        whispered = 0
        marked = 0
        net_errors = 0
        with httpx.Client(
            timeout=15,
            headers={"User-Agent": settings.mb_user_agent},
        ) as client:
            for i, (track, feat) in enumerate(candidates):
                if jobs.should_stop("lyrics", stop):
                    break
                try:
                    row, ratio = _fetch_lyrics(track, client)
                except httpx.HTTPError as exc:
                    # network outage — log the per-track failure, do not
                    # cache misses, abort soon
                    net_errors += 1
                    errors_svc.log_error(
                        track.video_id, "lyrics", f"network: {exc}"
                    )
                    if net_errors >= 10:
                        jobs.fail_job(
                            "lyrics", "network unavailable (10 consecutive errors)"
                        )
                        return
                    continue
                net_errors = 0
                # a definite outcome (found or a confident miss) clears
                # any earlier network error for this track
                errors_svc.clear_error(track.video_id, "lyrics")
                if row is not None:
                    with Session(engine) as session:
                        session.add(row)
                        if ratio >= CONFIRM_RATIO:
                            # a confident lyrics match itself proves vocals
                            _set_has_vocals(session, track.video_id, True)
                            confirmed += 1
                        session.commit()
                    found += 1
                else:
                    if feat is not None and feat.has_vocals is None:
                        verdict = _whisper_verdict(track, feat)
                        if verdict:
                            whispered += 1
                            found += 1
                            continue
                    # confident LRCLIB miss: remember it so the queue is
                    # not stuck on the same tracks at every run
                    with Session(engine) as session:
                        session.merge(
                            Lyrics(
                                track_id=track.video_id,
                                text="",
                                source="none",
                                fetched_at=datetime.utcnow(),
                            )
                        )
                        session.commit()
                    marked += 1
                if (i + 1) % 10 == 0 or i + 1 == total:
                    jobs.progress(
                        "lyrics",
                        i + 1,
                        total,
                        f"found {found} of {i + 1}; last: {track.title[:45]}",
                    )

        if jobs.should_stop("lyrics", stop):
            jobs.stop_job(
                "lyrics", detail=f"stopped; found {found} lyrics"
            )
            return
        jobs.finish_job(
            "lyrics",
            detail=(
                f"found {found} lyrics out of {total} checked "
                f"({confirmed} confirmed, {whispered} transcribed by whisper, "
                f"{marked} without lyrics)"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("lyrics", f"{type(exc).__name__}: {exc}")
        raise

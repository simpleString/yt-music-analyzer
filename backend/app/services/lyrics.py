import difflib
import json
import re
import threading
import time
from datetime import datetime

import httpx
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import AudioFeatures, Lyrics, Track
from app.services import jobs
from app.services.topics import extract_topics

LRCLIB_SEARCH = "https://lrclib.net/api/search"
MIN_MATCH_RATIO = 0.6

TITLE_JUNK_RE = re.compile(
    r"[([](official|lyrics?|lyric|audio|video|visualizer|remaster\w*|hd|hq|4k|mv"
    r"|explicit|clean|full version|version|premiere|премьера|официальн\w*"
    r"|live|session|studio|parody|пароди\w*|cover|кавер|remix|ремикс|radio edit"
    r"|outro|intro|bonus|re-?upload|reupload|full|tv anime|anime|amv"
    r"|[^)\]]*20\d{2}[^)\]]*)[^)\]]*[)\]]",
    re.I,
)
# «| Live From ...» — хвост после вертикальной черты с концертными маркерами
PIPE_TAIL_RE = re.compile(
    r"\s*[\|/]\s*(live|session|studio|from|official|version|edit|remix).*$", re.I
)
# ведущий номер трека: «23. », «6. », «07 - », «Track 3»
TRACK_NUM_RE = re.compile(r"^\s*(track\s*)?\d{1,2}[\s.\-_]+\s*", re.I)
# аниме/фандом-скобки: 【...】〖...〗｢...｣ и хвост после « × » (с пробелами,
# чтобы не рубить слова с латинской x вроде «Oxxxymiron»)
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
    # feat-хвосты и ведущие номера — уже после разделения на артиста/песню
    song = FEAT_RE.sub("", song).strip()
    song = TRACK_NUM_RE.sub("", song).strip()
    artist = FEAT_RE.sub("", artist).strip()
    # «Кожура/Я всё решу» — двойное название, берём первую часть
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
    t = (text or "").lower()
    cyr = len(re.findall(r"[а-яё]", t))
    lat = len(re.findall(r"[a-z]", t))
    if cyr > lat and cyr > 10:
        return "ru"
    if lat > 10:
        return "en"
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", t):
        return "cjk"
    return ""


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
    return re.sub(r"[^a-zа-яё0-9 ]", "", (s or "").lower()).strip()


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
    except (httpx.HTTPError, ValueError):
        return []


def _fetch_lyrics(track: Track, client: httpx.Client) -> Lyrics | None:
    artist_guess, song = _clean_title(track.title)
    artist = _artist_from_channel(track.channel) or artist_guess
    if not song:
        return None
    hits = _lrclib_search(song, artist, client)
    if not hits and artist and artist != artist_guess and artist_guess:
        # канал мог быть неточным (лейбл, лайв-канал) — пробуем артиста из названия
        hits = _lrclib_search(song, artist_guess, client)
    if not hits:
        # последний шанс: только по названию песни
        _throttle()
        try:
            resp = client.get(LRCLIB_SEARCH, params={"track_name": song[:120]})
            resp.raise_for_status()
            hits = resp.json()
        except (httpx.HTTPError, ValueError):
            hits = []
    best, best_ratio = None, 0.0
    target = _norm(f"{artist} {song}")
    for hit in hits[:8]:
        candidate = _norm(f"{hit.get('artistName', '')} {hit.get('trackName', '')}")
        ratio = difflib.SequenceMatcher(None, target, candidate).ratio()
        if ratio > best_ratio:
            best, best_ratio = hit, ratio
    if best is None or best_ratio < MIN_MATCH_RATIO:
        # без артиста в таргете — совпадение только названия
        target_song = _norm(song)
        for hit in hits[:8]:
            candidate = _norm(hit.get("trackName", ""))
            ratio = difflib.SequenceMatcher(None, target_song, candidate).ratio()
            if ratio > best_ratio:
                best, best_ratio = hit, ratio
    if best is None or best_ratio < MIN_MATCH_RATIO:
        return None
    text = best.get("plainLyrics") or ""
    if not text:
        return None
    language = detect_language(text)
    topics = extract_topics(text, language)
    return Lyrics(
        track_id=track.video_id,
        text=text,
        synced=bool(best.get("syncedLyrics")),
        source="lrclib",
        language=language,
        sentiment=sentiment_score(text),
        topics=json.dumps(topics, ensure_ascii=False) if topics else "",
        fetched_at=datetime.utcnow(),
    )


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
            candidates = [
                t
                for t, f in session.exec(stmt).all()
                if t.video_id not in have
                and (f.vocal_ratio is None or f.vocal_ratio >= settings.lyrics_min_vocal)
            ][: settings.lyrics_limit]

        total = len(candidates)
        jobs.progress(
            "lyrics", 0, total, f"к поиску: {total} (лимит {settings.lyrics_limit})"
            if total
            else "нет треков для поиска текстов",
        )

        found = 0
        with httpx.Client(
            timeout=15,
            headers={"User-Agent": settings.mb_user_agent},
        ) as client:
            for i, track in enumerate(candidates):
                if jobs.should_stop("lyrics", stop):
                    break
                row = _fetch_lyrics(track, client)
                if row is not None:
                    with Session(engine) as session:
                        session.add(row)
                        session.commit()
                    found += 1
                if (i + 1) % 10 == 0 or i + 1 == total:
                    jobs.progress(
                        "lyrics",
                        i + 1,
                        total,
                        f"найдено {found} из {i + 1}; последний: {track.title[:45]}",
                    )

        if jobs.should_stop("lyrics", stop):
            jobs.stop_job(
                "lyrics", detail=f"остановлено; найдено {found} текстов"
            )
            return
        jobs.finish_job(
            "lyrics",
            detail=f"найдено {found} текстов из {total} проверенных",
        )
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("lyrics", f"{type(exc).__name__}: {exc}")
        raise

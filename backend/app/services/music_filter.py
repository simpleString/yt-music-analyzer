import re
import threading

from sqlmodel import Session, select

from app.db import engine
from app.models import Track
from app.services import jobs
from app.services.artists import normalize_artist
from app.services.youtube import fetch_videos_details, has_api_key

STRONG_PATTERNS = [
    (r"official\s+(music\s+)?(video|audio|visualizer)", "official"),
    (r"\boficial\b|\bvideoclip\b|\bmusic\s+video\b", "music-video"),
    (r"\blyrics?\b|\bтекст\s+песни\b", "lyrics"),
    (r"\bfeat\.?\b|\bft\.?\b|\bпри уч\.", "feat"),
    (r"\bremix\b|\bremaster", "remix"),
    (r"\binstrumental\b|\bcover\b|\bcover-version\b|\bкавер\b", "cover"),
    (r"\blive\s+(at|on|в)\b|\bconcert\b|\bконцерт", "live"),
    (r"\bаудио\b|\(audio\)|\[audio\]", "audio"),
    (r"^\s*\d{2}\s*[–—-]\s*", "numbered"),
    (r"\bnightcore\b|\bmashup\b|\bbootleg\b|\bmix\b", "edit"),
    (r"\b(full\s+)?album\b|\bmixtape\b", "album"),
]
STRONG_COMPILED = [(re.compile(p, re.I), name) for p, name in STRONG_PATTERNS]
DASH_RE = re.compile(r"\s[–—-]\s")

NEGATIVE_RE = re.compile(
    r"сезон|сериал|фильм|эпизод|episode|трейлер|trailer|teaser|обзор|review"
    r"|gameplay|геймплей|стрим|twitch|подкаст|podcast|интервью|interview"
    r"|пранк|prank|челлендж|challenge|реакци|reaction|смешные|прикол|смешно"
    r"|выпуск|эфир|news|новости|разбор|туториал|tutorial|как\s+сделать"
    r"|amv|gmв|аниме|anime\s+episode"
    # tech and gadgets
    r"|наушник|смартфон|айфон|iphone|android|unboxing|распаковк"
    r"|сравнени|ванплас|oneplus|xiaomi|redmi|samsung|honor\b|huawei"
    r"|ноутбук|видеокарт|процессор|монитор|умные\s+часы|smartwatch"
    r"|buds\b|airdots|колонк"
    # development and education
    r"|godot|unity|unreal|python|javascript|typescript|java\b|c\+\+"
    r"|программи|кодинг|coding|нейросет|chatgpt|gpt-|llm"
    r"|курс|лекци|урок|lesson|вебинар|gamedev|разработ"
    r"|vlog|влог|day\s+in\s+(my\s+)?life"
    r"|top\s*\d|лучшие\s+\w+|vs\b",
    re.I,
)

# weak reasons: excluded from channel voting and re-evaluated
# on every filter run
WEAK_REASONS = (
    "artist-dash",
    "no-signal",
    "channel-music",
    "channel-not-music",
)
# what gets re-evaluated on a re-run (weak + pattern-dependent)
REEVALUATE_REASONS = WEAK_REASONS + ("anti-pattern",)

MUSIC_CATEGORY = 10
# 24/7 radio streams last "forever" (YouTube reports hundreds of thousands
# of hours); anything longer than 12 hours is not a single track
MAX_TRACK_SECONDS = 12 * 3600

CHANNEL_MIN_SAMPLES = 3
CHANNEL_MUSIC_SHARE = 0.8
CHANNEL_NOT_MUSIC_SHARE = 0.2


def classify_by_heuristics(title: str, channel: str) -> tuple[bool | None, str]:
    """Returns (is_music, reason). None = not sure, channel/API needed."""
    ch = (channel or "").lower()
    t = (title or "").strip()
    tl = t.lower()

    channel_reasons: list[str] = []
    if ch.endswith(" - topic") or ch.endswith("- topic"):
        channel_reasons.append("topic-channel")
    if "vevo" in ch:
        channel_reasons.append("vevo")

    strong_hits: list[str] = []
    for rx, name in STRONG_COMPILED:
        if rx.search(tl):
            strong_hits.append(name)

    if NEGATIVE_RE.search(tl):
        return False, "anti-pattern"

    if channel_reasons:
        return True, "+".join(dict.fromkeys(channel_reasons + strong_hits[:1]))
    if strong_hits:
        return True, "+".join(dict.fromkeys(strong_hits[:3]))
    if is_artist_channel_dash(t, channel or ""):
        return True, "artist-channel-dash"
    if is_artist_dash(t):
        return None, "artist-dash"
    return None, ""


def is_artist_dash(title: str) -> bool:
    """\"Artist - Track\": left side is short, without sentence punctuation."""
    t = (title or "").strip()
    if not DASH_RE.search(t):
        return False
    left = DASH_RE.split(t)[0].strip()
    if not left or len(left.split()) > 5:
        return False
    return not re.search(r"[?!:;…]", left)


def is_artist_channel_dash(title: str, channel: str) -> bool:
    """\"Husky - Bullet\" on the \"Husky\" channel: the artist posts their own tracks."""
    t = (title or "").strip()
    ch = (channel or "").strip()
    if not t or not ch:
        return False
    m = DASH_RE.search(t)
    if not m:
        return False
    left = t[: m.start()].strip()
    if not left:
        return False
    return left.casefold() == ch.casefold()


def run_filter(stop: threading.Event | None = None) -> None:
    try:
        if not jobs.start_job("filter"):
            return
        stop = stop if stop is not None else threading.Event()
        with Session(engine) as session:
            stmt = select(Track).where(
                (Track.is_music == None)  # noqa: E711
                | Track.music_reason.in_(REEVALUATE_REASONS)
                | (Track.music_reason == "")
            )
            tracks = session.exec(stmt).all()
            total = len(tracks)
            jobs.progress("filter", 0, total, f"{total} tracks to classify")

            n_music = n_not = 0

            # pass 1: confident signals
            undecided: list[Track] = []
            for t in tracks:
                verdict, reason = classify_by_heuristics(t.title, t.channel)
                if verdict is None:
                    undecided.append(t)
                else:
                    t.is_music = verdict
                    t.music_reason = reason
                    session.add(t)
                    if verdict:
                        n_music += 1
                    else:
                        n_not += 1
            session.commit()
            jobs.progress(
                "filter",
                n_music + n_not,
                total,
                f"heuristics: {n_music} music / {n_not} not music",
            )

            # channel voting: music share among the channel's confident tracks
            channel_stats = _channel_music_stats(session)

            def channel_verdict(t: Track) -> bool | None:
                ch = (t.channel or "").strip()
                if not ch:
                    return None
                stat = channel_stats.get(ch.lower())
                if stat is None:
                    return None
                n, music = stat
                if n < CHANNEL_MIN_SAMPLES:
                    return None
                share = music / n
                if share >= CHANNEL_MUSIC_SHARE:
                    return True
                if share <= CHANNEL_NOT_MUSIC_SHARE:
                    return False
                return None

            still_undecided: list[Track] = []
            n_dash_music = n_dash_not = 0
            for t in undecided:
                verdict = channel_verdict(t)
                if verdict is None:
                    still_undecided.append(t)
                    continue
                t.is_music = verdict
                t.music_reason = (
                    "channel-music" if verdict else "channel-not-music"
                )
                session.add(t)
                if verdict:
                    n_dash_music += 1
                else:
                    n_dash_not += 1
            session.commit()

            detail = (
                f"heuristics: {n_music} music / {n_not} not music; "
                f"channels: +{n_dash_music} / −{n_dash_not}"
            )
            undecided = still_undecided

            if undecided and has_api_key():
                api_chunk = 250
                n_api_music = 0
                n_api_done = 0
                for ci in range(0, len(undecided), api_chunk):
                    if jobs.should_stop("filter", stop):
                        break
                    group = undecided[ci : ci + api_chunk]
                    details = fetch_videos_details(
                        [t.video_id for t in group]
                    )
                    for t in group:
                        info = details.get(t.video_id)
                        if info is None:
                            t.is_music = False
                            t.music_reason = "api-miss"
                        else:
                            if info.get("duration") is not None:
                                t.duration = info["duration"]
                            if info.get("category_id") is not None:
                                t.category_id = info["category_id"]
                            if not t.channel and info.get("channel"):
                                t.channel = info["channel"]
                                t.artist_canonical = normalize_artist(t.channel)
                            dur = info.get("duration")
                            if info.get("category_id") != MUSIC_CATEGORY:
                                t.is_music = False
                                t.music_reason = "api:not-music"
                            elif dur is not None and dur > MAX_TRACK_SECONDS:
                                t.is_music = False
                                t.music_reason = "api:too-long"
                            else:
                                t.is_music = True
                                t.music_reason = "api:cat10"
                                n_api_music += 1
                        session.add(t)
                    session.commit()
                    n_api_done += len(group)
                    jobs.progress(
                        "filter",
                        min(total, n_music + n_not + n_api_done),
                        total,
                        f"YouTube API: {n_api_music} music out of {n_api_done}",
                    )
                detail += (
                    f"; YouTube API: {n_api_music} music out of {n_api_done}"
                )
            elif undecided:
                for t in undecided:
                    t.is_music = False
                    t.music_reason = "no-signal"
                session.commit()
                detail += f"; {len(undecided)} with no music signals"

            with Session(engine) as s2:
                final_music = len(
                    s2.exec(
                        select(Track.video_id).where(Track.is_music == True)  # noqa: E712
                    ).all()
                )
        if jobs.should_stop("filter", stop):
            jobs.stop_job("filter", detail=f"stopped ({detail})")
            return
        jobs.finish_job(
            "filter", detail=f"total music tracks: {final_music} ({detail})"
        )
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("filter", f"{type(exc).__name__}: {exc}")
        raise


def _channel_music_stats(session: Session) -> dict[str, tuple[int, int]]:
    """{channel_lower: (n_confident, n_music)} over tracks with confident verdicts.

    Confident: topic/vevo/yt-music-app, strong patterns, anti-pattern, API and
    manual verdicts. Weak ones (artist-dash, no-signal, channel-*) are excluded
    so that a channel's verdict does not reinforce itself.
    """
    rows = session.exec(
        select(Track.channel, Track.is_music, Track.music_reason)
    ).all()
    stats: dict[str, tuple[int, int]] = {}
    for channel, is_music, reason in rows:
        if not channel or is_music is None:
            continue
        if not reason or reason in WEAK_REASONS:
            continue
        key = channel.strip().lower()
        n, music = stats.get(key, (0, 0))
        stats[key] = (n + 1, music + (1 if is_music else 0))
    return stats

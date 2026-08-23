import re

from sqlmodel import Session, select

from app.db import engine
from app.models import Track
from app.services import jobs
from app.services.youtube import fetch_videos_details, has_api_key

STRONG_PATTERNS = [
    (r"official\s+(music\s+)?(video|audio|visualizer)", "official"),
    (r"\boficial\b|\bvideoclip\b|\bmusic\s+video\b", "music-video"),
    (r"\blyrics?\b|\bтекст\s+песни\b", "lyrics"),
    (r"\bfeat\.?\b|\bft\.?\b|\bпри уч\.", "feat"),
    (r"\bremix\b|\bremaster", "remix"),
    (r"\binstrumental\b|\bcover\b|\bcover-version\b|\bкавер\b", "cover"),
    (r"\blive\s+(at|в)\b|\bconcert\b|\bконцерт", "live"),
    (r"\bаудио\b|\(audio\)|\[audio\]", "audio"),
    (r"^\s*\d{2}\s*[–—-]\s*", "numbered"),
    (r"\bnightcore\b|\bmashup\b|\bbootleg\b|\bmix\b", "edit"),
]
STRONG_COMPILED = [(re.compile(p, re.I), name) for p, name in STRONG_PATTERNS]
DASH_RE = re.compile(r"\s[–—-]\s")

NEGATIVE_RE = re.compile(
    r"сезон|сериал|фильм|эпизод|episode|трейлер|trailer|teaser|обзор|review"
    r"|gameplay|геймплей|стрим|stream|подкаст|podcast|интервью|interview"
    r"|пранк|prank|челлендж|challenge|реакци|reaction|смешные|прикол|смешно"
    r"|выпуск|эфир|news|новости|разбор|туториал|tutorial|как\s+сделать"
    r"|amv|gmв|аниме|anime\s+episode",
    re.I,
)

MUSIC_CATEGORY = 10
MIN_DURATION = 60
MAX_DURATION = 600


def classify_by_heuristics(title: str, channel: str) -> tuple[bool | None, str]:
    """Возвращает (is_music, reason). None = не уверены, нужен YouTube API."""
    reasons: list[str] = []
    ch = (channel or "").lower()
    t = (title or "").strip()
    if ch.endswith(" - topic") or ch.endswith("- topic"):
        reasons.append("topic-channel")
    if "vevo" in ch:
        reasons.append("vevo")
    tl = t.lower()
    for rx, name in STRONG_COMPILED:
        if rx.search(tl):
            reasons.append(name)
    if DASH_RE.search(t):
        reasons.append("artist-dash")
    if any(k in ch for k in ("records", "recordings", "label")):
        reasons.append("label-channel")

    unique = list(dict.fromkeys(reasons))
    negative = bool(NEGATIVE_RE.search(tl))

    if negative:
        return False, "anti-pattern"
    if "topic-channel" in unique or "vevo" in unique:
        return True, "+".join(unique[:3])
    strong_hits = [r for r in unique if r != "artist-dash"]
    if len(strong_hits) >= 1:
        return True, "+".join((strong_hits + unique)[:3])
    if "artist-dash" in unique:
        return True, "artist-dash"
    return None, ""


def run_filter() -> None:
    try:
        if not jobs.start_job("filter"):
            return
        with Session(engine) as session:
            stmt = select(Track).where(Track.is_music == None)  # noqa: E711
            if has_api_key():
                stmt = select(Track).where(
                    (Track.is_music == None)  # noqa: E711
                    | (Track.music_reason == "no-signal")
                )
            tracks = session.exec(stmt).all()
            total = len(tracks)
            jobs.progress("filter", 0, total, f"{total} треков без классификации")

            undecided: list[Track] = []
            n_music = n_not = 0
            for t in tracks:
                verdict, reason = classify_by_heuristics(t.title, t.channel)
                if verdict is not None:
                    t.is_music = verdict
                    t.music_reason = reason
                    session.add(t)
                    if verdict:
                        n_music += 1
                    else:
                        n_not += 1
                else:
                    undecided.append(t)
            session.commit()

            detail = f"эвристики: {n_music} музыка / {n_not} не музыка"
            n_api_music = 0

            if undecided and has_api_key():
                ids = [t.video_id for t in undecided]
                details = fetch_videos_details(ids)
                for t in undecided:
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
                        ok = (
                            info.get("category_id") == MUSIC_CATEGORY
                            and info.get("duration") is not None
                            and MIN_DURATION <= info["duration"] <= MAX_DURATION
                        )
                        t.is_music = ok
                        t.music_reason = (
                            "api:cat10+dur" if ok else "api:not-music"
                        )
                        if ok:
                            n_api_music += 1
                    session.add(t)
                session.commit()
                detail += f"; YouTube API: {n_api_music} музыка из {len(undecided)}"
            elif undecided:
                for t in undecided:
                    t.is_music = False
                    t.music_reason = "no-signal"
                session.commit()
                detail += f"; {len(undecided)} без признаков музыки"

            with Session(engine) as s2:
                final_music = len(
                    s2.exec(
                        select(Track.video_id).where(Track.is_music == True)  # noqa: E712
                    ).all()
                )
        jobs.finish_job(
            "filter", detail=f"итого музыкальных треков: {final_music} ({detail})"
        )
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("filter", f"{type(exc).__name__}: {exc}")
        raise

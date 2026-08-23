import re
from datetime import datetime

from sqlalchemy import text
from sqlmodel import Session, select

from app.db import engine
from app.models import AudioFeatures, Track

RELAXED_RE = re.compile(
    r"unplugged|acoustic|акустик|piano|фортепиано|lo-?fi|chill|ambient|sleep|сон"
    r"|relax|спокой|колыбельн|lullaby|instrumental|инструментал|нежн|soft",
    re.I,
)
AGGRESSIVE_RE = re.compile(
    r"remix|nightcore|phonk|фонк|hard|hardcore|bass|boost|speed\s?up|edit|mashup"
    r"|bootleg|club|techno|rave|drum\s?and\s?bass|dnb|breakcore|banger|megamix"
    r"|dubstep|trap|metal|метал|рок|\brock\b|punk|панк|power",
    re.I,
)
SAD_RE = re.compile(
    r"\bsad\b|груст|печал|melanchol|меланхол|дожд|rain|зим|winter|tears|слез|слёз"
    r"|умир|умер|смерт|death|pain|боль|одинок|lonely|прощай|goodbye|пустот|alone",
    re.I,
)
HAPPY_RE = re.compile(
    r"happy|счаст|радост|весел|весёл|summer|лето|sun|солнц|dance|танц|party"
    r"|праздн|holiday|smile|улыбк|good\s?time",
    re.I,
)
LIVE_RE = re.compile(r"\blive\b|концерт|concert|session|\bmtv\b|radio", re.I)

MOODS = ("mood_happy", "mood_sad", "mood_relaxed", "mood_aggressive")


def _estimate(title: str, mean_hour: float, night_ratio: float) -> list[float]:
    t = title or ""
    if SAD_RE.search(t):
        return [0.15, 0.5, 0.25, 0.1]
    if RELAXED_RE.search(t):
        return [0.15, 0.2, 0.55, 0.1]
    if AGGRESSIVE_RE.search(t):
        return [0.2, 0.05, 0.05, 0.7]
    if HAPPY_RE.search(t):
        return [0.55, 0.1, 0.2, 0.15]
    if LIVE_RE.search(t):
        return [0.4, 0.1, 0.15, 0.35]
    if night_ratio > 0.55:
        return [0.15, 0.4, 0.35, 0.1]
    if 7 <= mean_hour < 12:
        return [0.45, 0.1, 0.25, 0.2]
    if 12 <= mean_hour < 18:
        return [0.35, 0.15, 0.25, 0.25]
    return [0.25, 0.2, 0.4, 0.15]


def ensure_meta_features() -> tuple[int, int]:
    """Создаёт предварительные (source='meta') фичи для музыкальных треков без фич.
    Возвращает (создано meta, всего треков с фичами)."""
    with Session(engine) as session:
        music_ids = set(
            session.exec(
                select(Track.video_id).where(Track.is_music == True)  # noqa: E712
            ).all()
        )
        have = set(
            session.exec(select(AudioFeatures.track_id)).all()  # type: ignore[arg-type]
        )
        todo = music_ids - have
        if not todo:
            total = len(have)
            return 0, total

        hour_stats = {}
        rows = session.execute(
            text(
                "SELECT track_id, "
                "AVG(CAST(strftime('%H', listened_at) AS REAL) "
                "+ CAST(strftime('%M', listened_at) AS REAL)/60.0) AS h, "
                "SUM(CASE WHEN CAST(strftime('%H', listened_at) AS INTEGER) >= 22 "
                "OR CAST(strftime('%H', listened_at) AS INTEGER) < 5 THEN 1 ELSE 0 END)"
                "*1.0/COUNT(*) AS nr "
                "FROM listen GROUP BY track_id"
            )
        ).all()
        for tid, h, nr in rows:
            hour_stats[tid] = (h or 12.0, nr or 0.0)

        titles = {
            t.video_id: (t.title, t.channel)
            for t in session.exec(select(Track)).all()
            if t.video_id in todo
        }

        created = 0
        now = datetime.utcnow()
        batch: list[AudioFeatures] = []
        for tid in todo:
            title, _ = titles.get(tid, ("", ""))
            mean_hour, night_ratio = hour_stats.get(tid, (12.0, 0.0))
            m = _estimate(title, mean_hour, night_ratio)
            batch.append(
                AudioFeatures(
                    track_id=tid,
                    source="meta",
                    tempo=0.0,
                    energy=0.0,
                    danceability=0.0,
                    acousticness=0.0,
                    brightness=0.0,
                    key="",
                    mode_conf=0.0,
                    mood_happy=m[0],
                    mood_sad=m[1],
                    mood_relaxed=m[2],
                    mood_aggressive=m[3],
                    analyzed_at=now,
                )
            )
            created += 1
            if len(batch) >= 1000:
                session.add_all(batch)
                session.commit()
                batch = []
        if batch:
            session.add_all(batch)
            session.commit()
        return created, len(have) + created

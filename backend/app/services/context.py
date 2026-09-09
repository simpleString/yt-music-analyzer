"""Time-context recommendations: "what fits right now".

Every track gets a histogram over listen hours and weekdays (from the
Listen table). The score for the current moment combines the smoothed
probability of hearing the track at this hour and on this weekday with
its overall popularity (log) and a penalty for very recent repeats.
"""

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlmodel import Session

from app.db import engine
from app.models import Track

WEEKDAY_NAMES = [
    "Mondays", "Tuesdays", "Wednesdays", "Thursdays",
    "Fridays", "Saturdays", "Sundays",
]

# share of a track's listens needed at this hour/weekday for a "often …" reason
REASON_SHARE = 0.25
REASON_MIN = 2


def _recency_penalty(last_at: datetime, now: datetime) -> float:
    """Repeats of the last day(s) are boring "right now"."""
    age = now - last_at
    if age < timedelta(hours=24):
        return 0.25
    if age < timedelta(hours=72):
        return 0.6
    return 1.0


def for_now(
    hour: int | None = None,
    weekday: int | None = None,
    limit: int = 12,
    date_from=None,
    date_to=None,
    tz_name: str = "",
) -> dict:
    """Top tracks for the given moment.

    hour: 0..23, weekday: 0=Mon..6=Sun; None — take from the browser
    timezone (tz_name, IANA), UTC as the last-resort fallback.
    date_from/date_to limit the listen history used for scoring.
    Returns {"hour", "weekday", "total", "items"}.
    """
    try:
        now_local = datetime.now(ZoneInfo(tz_name))
    except (ValueError, KeyError):
        now_local = datetime.now(dt_timezone.utc).replace(tzinfo=None)
    if hour is None:
        hour = now_local.hour
    if weekday is None:
        weekday = now_local.weekday()
    now_utc = datetime.utcnow()

    conds = "WHERE t.is_music = 1"
    params: dict = {"hh": f"{hour:02d}", "wd": weekday}
    if date_from is not None:
        conds += " AND l.listened_at >= :dfrom"
        params["dfrom"] = datetime.combine(date_from, datetime.min.time())
    if date_to is not None:
        conds += " AND l.listened_at < :dto"
        params["dto"] = datetime.combine(
            date_to + timedelta(days=1), datetime.min.time()
        )

    with Session(engine) as session:
        rows = session.execute(
            text(
                "SELECT l.track_id, "
                "SUM(CASE WHEN strftime('%H', l.listened_at) = :hh THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN (CAST(strftime('%w', l.listened_at) AS INTEGER) + 6) % 7 = :wd "
                "THEN 1 ELSE 0 END), "
                "COUNT(*), MAX(l.listened_at) "
                "FROM listen l JOIN track t ON t.video_id = l.track_id "
                + conds
                + " GROUP BY l.track_id"
            ),
            params,
        ).all()

        scored = []
        for track_id, at_hour, at_wd, total, raw_last in rows:
            last_at = (
                raw_last
                if isinstance(raw_last, datetime)
                else datetime.fromisoformat(str(raw_last))
            )
            total = int(total)
            at_hour = int(at_hour or 0)
            at_wd = int(at_wd or 0)
            p_hour = (at_hour + 1) / (total + 24)
            p_wd = (at_wd + 1) / (total + 7)
            score = (0.6 * p_hour + 0.4 * p_wd) * pow(
                total + 1, 0.5
            ) * _recency_penalty(last_at, now_utc)
            scored.append(
                (score, track_id, total, at_hour, at_wd, last_at)
            )
        scored.sort(key=lambda x: x[0], reverse=True)

        items = []
        for score, track_id, total, at_hour, at_wd, last_at in scored[:limit]:
            t = session.get(Track, track_id)
            if t is None:
                continue
            items.append(
                {
                    "track": {
                        "video_id": t.video_id,
                        "title": t.title,
                        "channel": t.channel,
                        "artist": t.artist_canonical or t.channel,
                        "play_count": t.play_count,
                    },
                    "plays": total,
                    "at_hour": at_hour,
                    "at_weekday": at_wd,
                    "score": round(score, 3),
                    "reason": _reason(hour, weekday, at_hour, at_wd, total),
                }
            )
        return {
            "hour": hour,
            "weekday": weekday,
            "total": len(scored),
            "items": items,
        }


def _reason(
    hour: int, weekday: int, at_hour: int, at_wd: int, total: int
) -> str:
    parts = []
    if at_hour >= REASON_MIN and at_hour / total >= REASON_SHARE:
        parts.append(f"often at {hour:02d}:00")
    if at_wd >= REASON_MIN and at_wd / total >= REASON_SHARE:
        parts.append(f"on {WEEKDAY_NAMES[weekday]}")
    return ", ".join(parts) if parts else "fits this time of day"

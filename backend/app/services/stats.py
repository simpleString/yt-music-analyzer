from datetime import date, datetime, timedelta

from sqlalchemy import func, text
from sqlmodel import Session, select

from app.models import Listen, Track

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
AVG_UNKNOWN_SECONDS = 210.0

ARTIST_EXPR = "COALESCE(NULLIF(t.artist_canonical, ''), t.channel)"


def _music_listen_join(
    date_from: date | None = None, date_to: date | None = None
) -> tuple[str, dict]:
    sql = "FROM listen l JOIN track t ON t.video_id = l.track_id WHERE t.is_music = 1"
    params: dict = {}
    if date_from is not None:
        sql += " AND l.listened_at >= :dfrom"
        params["dfrom"] = datetime.combine(date_from, datetime.min.time())
    if date_to is not None:
        sql += " AND l.listened_at < :dto"
        params["dto"] = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
    return sql, params


def totals(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> dict:
    join, params = _music_listen_join(date_from, date_to)
    period = date_from is not None or date_to is not None
    if period:
        music_ids = set()
    else:
        tracks_total = len(session.exec(select(Track.video_id)).all())  # type: ignore[arg-type]
        music = session.exec(
            select(Track.video_id).where(Track.is_music == True)  # noqa: E712
        ).all()
        music_ids = {v for v in music}
    listens_total = len(session.exec(select(Listen.id)).all())  # type: ignore[arg-type]
    music_listens = session.execute(
        text(f"SELECT COUNT(*), MIN(l.listened_at), MAX(l.listened_at) {join}"), params
    ).one()
    seconds = session.execute(
        text(
            "SELECT SUM(CASE WHEN t.duration IS NULL THEN :avg ELSE t.duration END) "
            + join
        ),
        {**params, "avg": AVG_UNKNOWN_SECONDS},
    ).scalar()
    analyzed = session.execute(text("SELECT COUNT(*) FROM audio_features")).scalar()
    period_tracks = (
        int(
            session.execute(
                text(f"SELECT COUNT(DISTINCT t.video_id) {join}"), params
            ).scalar()
            or 0
        )
        if period
        else None
    )
    return {
        "tracks_total": tracks_total if not period else period_tracks,
        "music_tracks": len(music_ids) if not period else period_tracks,
        "listens_total": listens_total,
        "music_listens": int(music_listens[0] or 0),
        "hours_est": round(float(seconds or 0) / 3600, 1),
        "first_listen": music_listens[1],
        "last_listen": music_listens[2],
        "analyzed": int(analyzed or 0),
    }


def top_artists(
    session: Session,
    limit: int = 12,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    join, params = _music_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            f"SELECT {ARTIST_EXPR} AS artist, COUNT(*) AS plays, "
            "COUNT(DISTINCT t.video_id) AS tracks "
            + join
            + f" AND {ARTIST_EXPR} != '' GROUP BY artist ORDER BY plays DESC LIMIT :lim"
        ),
        {**params, "lim": limit},
    ).all()
    return [
        {"channel": r[0], "plays": r[1], "tracks": r[2]} for r in rows
    ]


def top_tracks(
    session: Session,
    limit: int = 15,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    join, params = _music_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            "SELECT t.video_id, t.title, t.channel, COUNT(*) AS plays "
            + join
            + " GROUP BY t.video_id ORDER BY plays DESC LIMIT :lim"
        ),
        {**params, "lim": limit},
    ).all()
    return [
        {"video_id": r[0], "title": r[1], "channel": r[2], "plays": r[3]}
        for r in rows
    ]


def by_hour(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[str, int]]:
    join, params = _music_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            "SELECT strftime('%H', l.listened_at) AS h, COUNT(*) "
            + join
            + " GROUP BY h ORDER BY h"
        ),
        params,
    ).all()
    return [(r[0], r[1]) for r in rows]


def by_weekday(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[str, int]]:
    join, params = _music_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            "SELECT (CAST(strftime('%w', l.listened_at) AS INTEGER) + 6) % 7 AS wd, COUNT(*) "
            + join
            + " GROUP BY wd ORDER BY wd"
        ),
        params,
    ).all()
    return [(WEEKDAYS[r[0]], r[1]) for r in rows]


def by_month(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[str, int]]:
    join, params = _music_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            "SELECT strftime('%Y-%m', l.listened_at) AS m, COUNT(*) "
            + join
            + " GROUP BY m ORDER BY m"
        ),
        params,
    ).all()
    return [(r[0], r[1]) for r in rows]


def by_week(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[str, int]]:
    """Listens by week; label is the Monday date of that week."""
    join, params = _music_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            "SELECT strftime('%Y-%m-%d', l.listened_at, '-6 days', 'weekday 1') AS w, COUNT(*) "
            + join
            + " GROUP BY w ORDER BY w"
        ),
        params,
    ).all()
    return [(r[0], r[1]) for r in rows]

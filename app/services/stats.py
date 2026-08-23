from datetime import datetime

from sqlalchemy import func, text
from sqlmodel import Session, select

from app.models import Listen, Track

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
AVG_UNKNOWN_SECONDS = 210.0


def _music_listen_join():
    return (
        "FROM listen l JOIN track t ON t.video_id = l.track_id "
        "WHERE t.is_music = 1"
    )


def totals(session: Session) -> dict:
    tracks_total = len(session.exec(select(Track.video_id)).all())  # type: ignore[arg-type]
    music = session.exec(
        select(Track.video_id).where(Track.is_music == True)  # noqa: E712
    ).all()
    music_ids = {v for v in music}
    listens_total = len(session.exec(select(Listen.id)).all())  # type: ignore[arg-type]
    music_listens = session.execute(
        text(f"SELECT COUNT(*), MIN(l.listened_at), MAX(l.listened_at) {_music_listen_join()}")
    ).one()
    seconds = session.execute(
        text(
            "SELECT SUM(CASE WHEN t.duration IS NULL THEN :avg ELSE t.duration END) "
            + _music_listen_join()
        ),
        {"avg": AVG_UNKNOWN_SECONDS},
    ).scalar()
    analyzed = session.execute(text("SELECT COUNT(*) FROM audio_features")).scalar()
    return {
        "tracks_total": tracks_total,
        "music_tracks": len(music_ids),
        "listens_total": listens_total,
        "music_listens": int(music_listens[0] or 0),
        "hours_est": round(float(seconds or 0) / 3600, 1),
        "first_listen": music_listens[1],
        "last_listen": music_listens[2],
        "analyzed": int(analyzed or 0),
    }


def top_artists(session: Session, limit: int = 12) -> list[dict]:
    rows = session.execute(
        text(
            "SELECT t.channel, COUNT(*) AS plays, COUNT(DISTINCT t.video_id) AS tracks "
            + _music_listen_join()
            + " AND t.channel != '' GROUP BY t.channel ORDER BY plays DESC LIMIT :lim"
        ),
        {"lim": limit},
    ).all()
    return [
        {"channel": r[0], "plays": r[1], "tracks": r[2]} for r in rows
    ]


def top_tracks(session: Session, limit: int = 15) -> list[dict]:
    rows = session.execute(
        text(
            "SELECT t.video_id, t.title, t.channel, COUNT(*) AS plays "
            + _music_listen_join()
            + " GROUP BY t.video_id ORDER BY plays DESC LIMIT :lim"
        ),
        {"lim": limit},
    ).all()
    return [
        {"video_id": r[0], "title": r[1], "channel": r[2], "plays": r[3]}
        for r in rows
    ]


def by_hour(session: Session) -> list[tuple[str, int]]:
    rows = session.execute(
        text(
            "SELECT strftime('%H', l.listened_at) AS h, COUNT(*) "
            + _music_listen_join()
            + " GROUP BY h ORDER BY h"
        )
    ).all()
    return [(r[0], r[1]) for r in rows]


def by_weekday(session: Session) -> list[tuple[str, int]]:
    rows = session.execute(
        text(
            "SELECT (CAST(strftime('%w', l.listened_at) AS INTEGER) + 6) % 7 AS wd, COUNT(*) "
            + _music_listen_join()
            + " GROUP BY wd ORDER BY wd"
        )
    ).all()
    return [(WEEKDAYS[r[0]], r[1]) for r in rows]


def by_month(session: Session) -> list[tuple[str, int]]:
    rows = session.execute(
        text(
            "SELECT strftime('%Y-%m', l.listened_at) AS m, COUNT(*) "
            + _music_listen_join()
            + " GROUP BY m ORDER BY m"
        )
    ).all()
    return [(r[0], r[1]) for r in rows]

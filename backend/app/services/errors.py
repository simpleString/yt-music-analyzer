"""Per-track processing error log (table `track_error`).

Upsert on failure, delete on success: the table always holds only the
current problems, so the UI can show "what exactly is broken".
"""

from datetime import datetime, timezone as dt_timezone

from sqlmodel import Session, select

from app.db import engine
from app.models import Track, TrackError

ERROR_MAX_LEN = 300


def _iso_utc(dt: datetime) -> str:
    """created_at is stored as naive UTC — add the explicit offset so the
    browser renders it in the user's local timezone, not as UTC."""
    return dt.replace(tzinfo=dt_timezone.utc).isoformat()


def log_error(video_id: str, stage: str, error: str) -> None:
    with Session(engine) as session:
        session.merge(
            TrackError(
                video_id=video_id,
                stage=stage,
                error=(error or "unknown error")[:ERROR_MAX_LEN],
                created_at=datetime.utcnow(),
            )
        )
        session.commit()


def clear_error(video_id: str, stage: str) -> None:
    with Session(engine) as session:
        row = session.get(TrackError, (video_id, stage))
        if row is not None:
            session.delete(row)
            session.commit()


def clear_all(video_id: str) -> None:
    with Session(engine) as session:
        for row in session.exec(
            select(TrackError).where(TrackError.video_id == video_id)
        ).all():
            session.delete(row)
        session.commit()


def track_errors(video_id: str) -> list[dict]:
    """Errors of a single track (for the track card)."""
    with Session(engine) as session:
        rows = session.exec(
            select(TrackError)
            .where(TrackError.video_id == video_id)
            .order_by(TrackError.created_at.desc())
        ).all()
    return [
        {
            "stage": r.stage,
            "error": r.error,
            "created_at": _iso_utc(r.created_at),
        }
        for r in rows
    ]


def list_errors(limit: int = 200) -> list[dict]:
    """All current errors with track info, newest first."""
    with Session(engine) as session:
        rows = session.exec(
            select(TrackError, Track)
            .join(Track, Track.video_id == TrackError.video_id)  # type: ignore[call-arg]
            .order_by(TrackError.created_at.desc())
            .limit(limit)
        ).all()
    return [
        {
            "video_id": te.video_id,
            "title": t.title,
            "channel": t.channel,
            "artist": t.artist_canonical or t.channel,
            "stage": te.stage,
            "error": te.error,
            "created_at": _iso_utc(te.created_at),
        }
        for te, t in rows
    ]

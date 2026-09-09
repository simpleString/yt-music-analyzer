import threading
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.db import engine
from app.models import AppMeta, Job

KINDS = ("import", "filter", "audio", "clusters", "lyrics", "mb-genres", "sessions")

# a job whose progress hasn't been updated for longer than this is
# considered dead (its thread died with the server restart) and may be
# restarted
STALE_AFTER = timedelta(minutes=10)

# cancel flag is stored in the DB: the job may be running in another process
CANCEL_PREFIX = "cancel:"

_cancel_events: dict[str, threading.Event] = {}


def register_cancel(kind: str) -> threading.Event:
    """Registers a cancel event for the job being started."""
    ev = threading.Event()
    _cancel_events[kind] = ev
    return ev


def _clear_cancel_flag(session: Session, kind: str) -> None:
    row = session.get(AppMeta, CANCEL_PREFIX + kind)
    if row is not None:
        session.delete(row)


def cancel_requested(kind: str) -> bool:
    """True if cancellation was requested (in-memory event and/or DB flag)."""
    ev = _cancel_events.get(kind)
    if ev is not None and ev.is_set():
        return True
    with Session(engine) as session:
        return get_meta(session, CANCEL_PREFIX + kind) is not None


def should_stop(kind: str, stop: threading.Event | None = None) -> bool:
    """Single stop check for workers: local Event + DB flag."""
    if stop is not None and stop.is_set():
        return True
    return cancel_requested(kind)


def request_cancel(kind: str) -> bool:
    """Asks the job to stop. False — the job is not running.

    The flag is written to the DB, so even a job started by another
    process (e.g. a background run) gets stopped.
    """
    with Session(engine) as session:
        job = get_job(session, kind)
        if job is None or job.status != "running":
            return False
        if _now() - job.updated_at >= STALE_AFTER:
            # the job hasn't reported progress in a while: clear the
            # record right away to unlock the start button, but keep the
            # cancel flag — if the thread is alive (just slow without
            # progress), it will stop
            job.status = "cancelled"
            job.detail = "stopped (job was unresponsive)"
            job.updated_at = _now()
            session.add(job)
            set_meta(session, CANCEL_PREFIX + kind, "1")
            session.commit()
        else:
            set_meta(session, CANCEL_PREFIX + kind, "1")
            session.commit()
    ev = _cancel_events.get(kind)
    if ev is not None:
        ev.set()
    return True


def clear_cancel(kind: str) -> None:
    _cancel_events.pop(kind, None)


def _now() -> datetime:
    return datetime.utcnow()


def get_job(session: Session, kind: str) -> Job | None:
    return session.exec(
        select(Job).where(Job.kind == kind).order_by(Job.id.desc())
    ).first()


def is_running(session: Session, kind: str) -> bool:
    job = get_job(session, kind)
    if job is None or job.status != "running":
        return False
    return _now() - job.updated_at < STALE_AFTER


def start_job(kind: str, total: int = 0) -> bool:
    with Session(engine) as session:
        if is_running(session, kind):
            return False
        job = get_job(session, kind)
        if job is None:
            job = Job(kind=kind)
            session.add(job)
            session.commit()
            session.refresh(job)
        job.status = "running"
        job.total = total
        job.done = 0
        job.detail = ""
        job.error = ""
        job.updated_at = _now()
        _clear_cancel_flag(session, kind)
        session.add(job)
        session.commit()
        return True


def finish_job(kind: str, detail: str = "") -> None:
    with Session(engine) as session:
        job = get_job(session, kind)
        if job is None:
            return
        job.status = "done"
        job.detail = detail
        job.updated_at = _now()
        _clear_cancel_flag(session, kind)
        session.add(job)
        session.commit()


def fail_job(kind: str, error: str) -> None:
    with Session(engine) as session:
        job = get_job(session, kind)
        if job is None:
            return
        job.status = "error"
        job.error = error[:2000]
        job.updated_at = _now()
        _clear_cancel_flag(session, kind)
        session.add(job)
        session.commit()


def stop_job(kind: str, detail: str = "") -> None:
    """Marks the job as stopped by the user."""
    with Session(engine) as session:
        job = get_job(session, kind)
        if job is None:
            return
        job.status = "cancelled"
        job.detail = detail or "stopped by user"
        job.updated_at = _now()
        _clear_cancel_flag(session, kind)
        session.add(job)
        session.commit()


def cancel_orphans() -> None:
    """On app startup: threads of the previous process are already dead.

    Orphaned "running" records block the buttons until STALE_AFTER
    expires — mark them cancelled right away.
    """
    with Session(engine) as session:
        rows = session.exec(
            select(Job).where(Job.status == "running")
        ).all()
        for job in rows:
            job.status = "cancelled"
            job.detail = "interrupted by server restart"
            job.updated_at = _now()
            session.add(job)
        if rows:
            session.commit()


def progress(kind: str, done: int, total: int, detail: str = "") -> None:
    with Session(engine) as session:
        job = get_job(session, kind)
        if job is None:
            return
        job.done = done
        job.total = total
        job.detail = detail
        job.updated_at = _now()
        session.add(job)
        session.commit()


def get_meta(session: Session, key: str) -> str | None:
    row = session.get(AppMeta, key)
    return row.value if row else None


def set_meta(session: Session, key: str, value: str) -> None:
    row = session.get(AppMeta, key)
    if row is None:
        row = AppMeta(key=key, value=value)
    else:
        row.value = value
    session.add(row)


def quota_key() -> str:
    return f"yt_quota_{date.today().isoformat()}"

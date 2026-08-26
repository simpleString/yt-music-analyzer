from datetime import date, datetime

from sqlmodel import Session, select

from app.db import engine
from app.models import AppMeta, Job

KINDS = ("import", "filter", "audio", "clusters", "lyrics")


def _now() -> datetime:
    return datetime.utcnow()


def get_job(session: Session, kind: str) -> Job | None:
    return session.exec(
        select(Job).where(Job.kind == kind).order_by(Job.id.desc())
    ).first()


def is_running(session: Session, kind: str) -> bool:
    job = get_job(session, kind)
    return job is not None and job.status == "running"


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
        session.add(job)
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

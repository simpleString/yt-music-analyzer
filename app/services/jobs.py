import threading
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.db import engine
from app.models import AppMeta, Job

KINDS = ("import", "filter", "audio", "clusters", "lyrics")

# задание, чей прогресс не обновлялся дольше этого, считается мёртвым
# (поток умер вместе с перезапуском сервера) и может быть перезапущено
STALE_AFTER = timedelta(minutes=10)

# флаг отмены хранится в БД: задание может выполняться в другом процессе
CANCEL_PREFIX = "cancel:"

_cancel_events: dict[str, threading.Event] = {}


def register_cancel(kind: str) -> threading.Event:
    """Регистрирует событие отмены для запускаемого задания."""
    ev = threading.Event()
    _cancel_events[kind] = ev
    return ev


def _clear_cancel_flag(session: Session, kind: str) -> None:
    row = session.get(AppMeta, CANCEL_PREFIX + kind)
    if row is not None:
        session.delete(row)


def cancel_requested(kind: str) -> bool:
    """True, если отмена запрошена (событие в памяти и/или флаг в БД)."""
    ev = _cancel_events.get(kind)
    if ev is not None and ev.is_set():
        return True
    with Session(engine) as session:
        return get_meta(session, CANCEL_PREFIX + kind) is not None


def should_stop(kind: str, stop: threading.Event | None = None) -> bool:
    """Единая проверка остановки для воркеров: локальный Event + флаг БД."""
    if stop is not None and stop.is_set():
        return True
    return cancel_requested(kind)


def request_cancel(kind: str) -> bool:
    """Просит задание остановиться. False — задание не выполняется.

    Флаг пишется в БД, поэтому останавливается даже задание,
    запущенное другим процессом (например, фоновым прогоном).
    """
    with Session(engine) as session:
        job = get_job(session, kind)
        if job is None or job.status != "running":
            return False
        if _now() - job.updated_at >= STALE_AFTER:
            # мёртвое задание: гасим сразу, чтобы разблокировать кнопку запуска
            job.status = "cancelled"
            job.detail = "остановлено (задание не отвечало)"
            job.updated_at = _now()
            session.add(job)
            _clear_cancel_flag(session, kind)
            session.commit()
            return True
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
    """Помечает задание остановленным пользователем."""
    with Session(engine) as session:
        job = get_job(session, kind)
        if job is None:
            return
        job.status = "cancelled"
        job.detail = detail or "остановлено пользователем"
        job.updated_at = _now()
        _clear_cancel_flag(session, kind)
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

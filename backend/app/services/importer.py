import threading
from collections import Counter

from sqlalchemy import func, text
from sqlmodel import Session, select

from app.db import engine
from app.models import Listen, Track
from app.parsers.takeout import RawListen, load_history_file, parse_watch_history
from app.services import jobs
from app.services.artists import normalize_artist

BATCH = 500


def run_import(
    filepath: str,
    stop: threading.Event | None = None,
    tz_name: str = "",
) -> None:
    try:
        if not jobs.start_job("import"):
            return
        stop = stop if stop is not None else threading.Event()
        data = load_history_file(filepath)
        # tz always comes from the browser; UTC is the last-resort fallback
        entries = parse_watch_history(data, tz_name or "UTC")

        seen: set[tuple[str, int]] = set()
        unique: list[RawListen] = []
        for e in entries:
            k = (e.video_id, int(e.listened_at.timestamp()))
            if k in seen:
                continue
            seen.add(k)
            unique.append(e)

        with Session(engine) as session:
            existing = set(
                session.exec(
                    select(Listen.track_id, Listen.listened_at)
                ).all()  # type: ignore[arg-type]
            )
            existing = {(t, int(dt.timestamp())) for t, dt in existing}

            tracks: dict[str, Track] = {}
            new_listens: list[Listen] = []
            for e in unique:
                if (e.video_id, int(e.listened_at.timestamp())) in existing:
                    continue
                track = tracks.get(e.video_id)
                if track is None:
                    track = session.get(Track, e.video_id) or Track(
                        video_id=e.video_id
                    )
                    tracks[e.video_id] = track
                track.title = e.title or track.title
                track.channel = e.channel or track.channel
                if track.channel:
                    track.artist_canonical = normalize_artist(track.channel)
                track.header = e.header
                if e.header == "YouTube Музыка" and track.is_music is None:
                    track.is_music = True
                    track.music_reason = "yt-music-app"
                session.add(track)
                new_listens.append(
                    Listen(track_id=e.video_id, listened_at=e.listened_at)
                )
                if len(new_listens) >= BATCH:
                    session.add_all(new_listens)
                    session.commit()
                    # free the identity map: otherwise all Listen/Track
                    # objects pile up in the session until the end of the
                    # import (memory leak → OOM)
                    session.expunge_all()
                    # committed tracks are expired AND detached now —
                    # keeping them in the memo would blow up the next
                    # attribute read with DetachedInstanceError; the
                    # session.get() above re-selects them instead
                    tracks.clear()
                    new_listens = []
                    if jobs.should_stop("import", stop):
                        break
            if jobs.should_stop("import", stop):
                jobs.stop_job(
                    "import", detail="stopped by user (partial import)"
                )
                return

            if new_listens:
                session.add_all(new_listens)
            session.commit()

            session.execute(
                text(
                    "UPDATE track SET play_count = "
                    "(SELECT COUNT(*) FROM listen WHERE listen.track_id = track.video_id)"
                )
            )
            session.commit()

            n_tracks = session.exec(select(func.count()).select_from(Track)).one()
            n_listens = session.exec(select(func.count()).select_from(Listen)).one()
            added = Counter(e.video_id for e in unique)

        jobs.finish_job(
            "import",
            detail=(
                f"{len(unique)} history entries, {len(added)} unique videos; "
                f"in DB: {n_tracks} tracks, {n_listens} listens"
            ),
        )
        # fresh listens change sessions: rebuild co-occurrence + Markov
        from app.services import sessions

        sessions.rebuild_in_background()
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("import", f"{type(exc).__name__}: {exc}")
        raise

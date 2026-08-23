from collections import Counter

from sqlalchemy import text
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import Listen, Track
from app.parsers.takeout import RawListen, load_history_file, parse_watch_history
from app.services import jobs

BATCH = 500


def run_import(filepath: str) -> None:
    try:
        if not jobs.start_job("import"):
            return
        data = load_history_file(filepath)
        entries = parse_watch_history(data, settings.timezone)

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
                    new_listens = []

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

            n_tracks = len(
                session.exec(select(Track.video_id)).all()  # type: ignore[arg-type]
            )
            n_listens = len(
                session.exec(select(Listen.id)).all()  # type: ignore[arg-type]
            )
            added = Counter(e.video_id for e in unique)

        jobs.finish_job(
            "import",
            detail=(
                f"{len(unique)} записей истории, {len(added)} уникальных видео; "
                f"в БД: {n_tracks} треков, {n_listens} прослушиваний"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("import", f"{type(exc).__name__}: {exc}")
        raise

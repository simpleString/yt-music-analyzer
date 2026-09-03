from sqlmodel import SQLModel, Session, create_engine, select

from app.config import settings

engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


def init_db() -> None:
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        from sqlalchemy import text

        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(audio_features)"))]
        if "source" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE audio_features "
                    "ADD COLUMN source VARCHAR NOT NULL DEFAULT 'audio'"
                )
            )
        migrations = {
            "mfcc": "ALTER TABLE audio_features ADD COLUMN mfcc VARCHAR NOT NULL DEFAULT ''",
            "chroma": "ALTER TABLE audio_features ADD COLUMN chroma VARCHAR NOT NULL DEFAULT ''",
            "contrast": "ALTER TABLE audio_features ADD COLUMN contrast VARCHAR NOT NULL DEFAULT ''",
            "dynamics": "ALTER TABLE audio_features ADD COLUMN dynamics FLOAT",
            "loudness": "ALTER TABLE audio_features ADD COLUMN loudness FLOAT",
            "percussive": "ALTER TABLE audio_features ADD COLUMN percussive FLOAT",
            "tags": "ALTER TABLE audio_features ADD COLUMN tags VARCHAR NOT NULL DEFAULT ''",
            "vocal_ratio": "ALTER TABLE audio_features ADD COLUMN vocal_ratio FLOAT",
            "mood_epic": "ALTER TABLE audio_features ADD COLUMN mood_epic FLOAT NOT NULL DEFAULT 0.125",
            "mood_dark": "ALTER TABLE audio_features ADD COLUMN mood_dark FLOAT NOT NULL DEFAULT 0.125",
            "mood_romantic": "ALTER TABLE audio_features ADD COLUMN mood_romantic FLOAT NOT NULL DEFAULT 0.125",
            "mood_atmospheric": (
                "ALTER TABLE audio_features ADD COLUMN mood_atmospheric "
                "FLOAT NOT NULL DEFAULT 0.125"
            ),
            "mood_electronic": (
                "ALTER TABLE audio_features ADD COLUMN mood_electronic "
                "FLOAT NOT NULL DEFAULT 0.125"
            ),
            "mood_acoustic": (
                "ALTER TABLE audio_features ADD COLUMN mood_acoustic "
                "FLOAT NOT NULL DEFAULT 0.125"
            ),
            "mood_party": (
                "ALTER TABLE audio_features ADD COLUMN mood_party "
                "FLOAT NOT NULL DEFAULT 0.125"
            ),
            "embedding": (
                "ALTER TABLE audio_features ADD COLUMN embedding "
                "VARCHAR NOT NULL DEFAULT ''"
            ),
            "feat_version": (
                "ALTER TABLE audio_features ADD COLUMN feat_version "
                "INTEGER NOT NULL DEFAULT 0"
            ),
        }
        for col, ddl in migrations.items():
            if col not in cols:
                conn.execute(text(ddl))
        track_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(track)"))]
        if "artist_canonical" not in track_cols:
            conn.execute(
                text(
                    "ALTER TABLE track "
                    "ADD COLUMN artist_canonical VARCHAR NOT NULL DEFAULT ''"
                )
            )
        lyrics_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(lyrics)"))]
        if "topics" not in lyrics_cols:
            conn.execute(
                text(
                    "ALTER TABLE lyrics "
                    "ADD COLUMN topics VARCHAR NOT NULL DEFAULT ''"
                )
            )
        conn.commit()
        _backfill_artists()
        _backfill_topics()


def _backfill_topics() -> None:
    import json

    from app.models import Lyrics
    from app.services.topics import extract_topics

    with Session(engine) as session:
        rows = session.exec(
            select(Lyrics.track_id, Lyrics.text, Lyrics.language).where(  # type: ignore[arg-type]
                Lyrics.topics == ""
            )
        ).all()
        for track_id, text, language in rows:
            row = session.get(Lyrics, track_id)
            if row is None:
                continue
            topics = extract_topics(text, language)
            if topics:
                row.topics = json.dumps(topics, ensure_ascii=False)
                session.add(row)
        session.commit()


def _backfill_artists() -> None:
    from app.models import Track
    from app.services.artists import normalize_artist

    with Session(engine) as session:
        rows = session.exec(
            select(Track.video_id, Track.channel).where(  # type: ignore[arg-type]
                Track.artist_canonical == ""
            )
        ).all()
        for video_id, channel in rows:
            track = session.get(Track, video_id)
            if track is None:
                continue
            track.artist_canonical = normalize_artist(track.channel)
            session.add(track)
        session.commit()


def get_session() -> Session:
    return Session(engine)

from sqlmodel import SQLModel, Session, create_engine

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
            "feat_version": (
                "ALTER TABLE audio_features ADD COLUMN feat_version "
                "INTEGER NOT NULL DEFAULT 0"
            ),
        }
        for col, ddl in migrations.items():
            if col not in cols:
                conn.execute(text(ddl))
        conn.commit()


def get_session() -> Session:
    return Session(engine)

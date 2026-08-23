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
        conn.commit()


def get_session() -> Session:
    return Session(engine)

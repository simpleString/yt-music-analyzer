from datetime import datetime

from sqlmodel import Field, SQLModel


class Track(SQLModel, table=True):
    __tablename__ = "track"
    video_id: str = Field(primary_key=True)
    title: str = ""
    channel: str = ""
    header: str = ""
    duration: float | None = None
    category_id: int | None = None
    is_music: bool | None = None
    music_reason: str = ""
    play_count: int = 0
    cluster_id: int | None = Field(default=None, foreign_key="cluster.id")


class Listen(SQLModel, table=True):
    __tablename__ = "listen"
    id: int | None = Field(default=None, primary_key=True)
    track_id: str = Field(foreign_key="track.video_id", index=True)
    listened_at: datetime = Field(index=True)


class AudioFeatures(SQLModel, table=True):
    __tablename__ = "audio_features"
    track_id: str = Field(primary_key=True, foreign_key="track.video_id")
    source: str = "audio"
    tempo: float = 0.0
    energy: float = 0.0
    danceability: float = 0.0
    acousticness: float = 0.0
    brightness: float = 0.0
    mood_happy: float = 0.25
    mood_sad: float = 0.25
    mood_relaxed: float = 0.25
    mood_aggressive: float = 0.25
    key: str = ""
    mode_conf: float = 0.5
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)


class Cluster(SQLModel, table=True):
    __tablename__ = "cluster"
    id: int | None = Field(default=None, primary_key=True)
    name: str = ""
    centroid: str = "[]"
    size: int = 0


class Job(SQLModel, table=True):
    __tablename__ = "job"
    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    status: str = "pending"
    total: int = 0
    done: int = 0
    detail: str = ""
    error: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AppMeta(SQLModel, table=True):
    __tablename__ = "appmeta"
    key: str = Field(primary_key=True)
    value: str = ""

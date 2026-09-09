from datetime import datetime

from sqlmodel import Field, SQLModel


class Track(SQLModel, table=True):
    __tablename__ = "track"
    video_id: str = Field(primary_key=True)
    title: str = ""
    channel: str = ""
    artist_canonical: str = ""
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
    mood_happy: float = 0.125
    mood_sad: float = 0.125
    mood_relaxed: float = 0.125
    mood_aggressive: float = 0.125
    mood_electronic: float = 0.125
    mood_acoustic: float = 0.125
    mood_party: float = 0.125
    mood_epic: float = 0.125
    mood_dark: float = 0.125
    mood_romantic: float = 0.125
    mood_atmospheric: float = 0.125
    key: str = ""
    mode_conf: float = 0.5
    # v2 features (feat_version=2): json arrays and scalars
    mfcc: str = ""
    chroma: str = ""
    contrast: str = ""
    dynamics: float | None = None
    loudness: float | None = None
    percussive: float | None = None
    # v3 features (Essentia): tags json and vocal ratio
    tags: str = ""
    vocal_ratio: float | None = None
    # whisper verdict ("are there words?"): True/False, None = not checked
    has_vocals: bool | None = None
    embedding: str = ""
    feat_version: int = 0
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)


class Lyrics(SQLModel, table=True):
    __tablename__ = "lyrics"
    track_id: str = Field(primary_key=True, foreign_key="track.video_id")
    text: str = ""
    synced: bool = False
    source: str = ""
    language: str = ""
    sentiment: float = 0.0
    topics: str = ""
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


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


class YtmMeta(SQLModel, table=True):
    __tablename__ = "ytm_meta"
    # extra track metadata from YouTube Music catalog (get_song)
    track_id: str = Field(primary_key=True, foreign_key="track.video_id")
    album: str = ""
    album_id: str = ""
    year: str = ""
    # json list of {name, id}
    artists: str = "[]"
    # json list of {url, width, height}
    thumbnails: str = "[]"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class YtmSimilar(SQLModel, table=True):
    __tablename__ = "ytm_similar"
    # YouTube-native "radio" recommendations seeded by this track
    seed_video_id: str = Field(primary_key=True, foreign_key="track.video_id")
    # json list of {video_id, title, artist, album, thumbnail, duration}
    payload: str = "[]"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class MbArtist(SQLModel, table=True):
    __tablename__ = "mb_artist"
    # MusicBrainz artist info (genres/tags/country/life span), keyed by the
    # canonical artist name; empty mbid = "not found" miss (shorter TTL)
    name: str = Field(primary_key=True)
    mbid: str = ""
    # json: {name, disambiguation, country, type, life_span, genres, tags}
    payload: str = "[]"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class TrackError(SQLModel, table=True):
    __tablename__ = "track_error"
    # last processing error per track and pipeline stage ("audio", "lyrics");
    # the row is removed as soon as the stage succeeds — only actual
    # problems are kept here
    video_id: str = Field(primary_key=True, foreign_key="track.video_id")
    stage: str = Field(primary_key=True)
    error: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Cooccur(SQLModel, table=True):
    __tablename__ = "cooccur"
    # pair listened within one session; track_a < track_b (video_id order)
    track_a: str = Field(primary_key=True, foreign_key="track.video_id")
    track_b: str = Field(primary_key=True, foreign_key="track.video_id")
    cnt: int = 0
    last_at: datetime | None = None


class NextTrack(SQLModel, table=True):
    __tablename__ = "next_track"
    # Markov transition prev -> next within a session (time gap capped)
    cur: str = Field(primary_key=True, foreign_key="track.video_id")
    nxt: str = Field(primary_key=True, foreign_key="track.video_id")
    cnt: int = 0
    last_at: datetime | None = None


class LbSimilar(SQLModel, table=True):
    __tablename__ = "lb_similar"
    # ListenBrainz global similar artists, keyed by source artist MBID;
    # json list of {name, mbid}
    mbid: str = Field(primary_key=True)
    payload: str = "[]"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

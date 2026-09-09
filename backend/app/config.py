from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    youtube_api_key: str = ""
    youtube_daily_quota: int = 10000
    data_dir: Path = Path("data")
    frontend_dist: Path = _REPO_ROOT / "frontend" / "dist"
    audio_analysis_limit: int = 5
    # listen-count threshold: tracks with fewer listens are skipped
    # during audio analysis and lyrics fetching
    min_play_count: int = 2
    analyze_full_max: int = 300
    audio_workers: int = 2
    # parallel analysis threads when audio is already cached (no network
    # needed); the bottleneck is CPU: raise to a sensible number of cores
    audio_workers_cached: int = 8
    audio_delete_after: bool = False
    # cluster in the Discogs-EffNet embedding space (cosine-like) instead
    # of the weighted v2 blocks (timbre/rhythm/harmony/macro)
    cluster_use_embedding: bool = False
    mb_user_agent: str = (
        "yt-music-analyzer/1.0 (local personal project; contact: example@example.com)"
    )
    mb_enabled: bool = True
    # MusicBrainz artist info: cache TTL (not-found rows live shorter)
    mb_cache_days: int = 30
    # artist prefill job: how many top artists per run (0 — all)
    mb_prefill_limit: int = 0
    # lyrics lookup: how many tracks per run, 0 — all eligible
    lyrics_limit: int = 0
    # vocal score (voice_instrumental head, fallback: Jamendo "Voice"
    # instrument) above which a track counts as vocal without a whisper
    # spot-check; also the fallback for the "instrumental" filter when
    # the whisper verdict is unknown
    lyrics_min_vocal: float = 0.3
    # whisper spot-check ("are there words?"): runs when LRCLIB found
    # nothing and the vocal score is below lyrics_min_vocal
    whisper_model: str = "base"
    # recognized words in the fragment for the track to count as vocal
    whisper_min_words: int = 8
    whisper_clip_seconds: int = 45
    audio_cookies_from_browser: str = "chrome"
    audio_cookies_keyring: str = "basictext"
    # YouTube Music (unofficial API, no key/auth needed for browsing):
    # extra track metadata + YouTube-native "similar" recommendations
    ytm_enabled: bool = True
    ytm_language: str = "en"
    # cache TTL for fetched data; stale rows are refetched on demand
    ytm_cache_days: int = 7
    # how many similar tracks to request from the watch playlist
    ytm_limit: int = 25
    # min interval between YT Music requests (seconds), polite throttling
    ytm_throttle: float = 0.7
    # listening sessions: a gap above this many minutes starts a new one
    session_gap_min: int = 45
    # sessions with more unique tracks than this are treated as 24/7
    # radio streams: co-occurrence pairs are skipped (quadratic cost)
    session_max_tracks: int = 200
    # Markov transitions: consecutive listens with a gap above this are
    # not counted (user walked away mid-session)
    markov_gap_min: int = 15
    # recency decay for co-occurrence scores (score halves every N days)
    cooccur_half_life_days: int = 180
    # ListenBrainz Labs (global similar artists, no key): enabled + cache TTL
    lb_enabled: bool = True
    lb_cache_days: int = 30
    # minimum key confidence for harmonic-mixing compatibility
    mix_key_conf: float = 0.7

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.audio_dir,
            self.uploads_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()

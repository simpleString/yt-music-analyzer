from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    youtube_api_key: str = ""
    youtube_daily_quota: int = 10000
    timezone: str = "Europe/Moscow"
    data_dir: Path = Path("data")
    frontend_dist: Path = _REPO_ROOT / "frontend" / "dist"
    audio_analysis_limit: int = 5
    analyze_full_max: int = 300
    audio_workers: int = 2
    # параллельных потоков анализа, когда аудио уже в кэше (сеть не нужна);
    # узкое место — CPU: повышай до разумного числа ядер
    audio_workers_cached: int = 8
    audio_delete_after: bool = False
    cluster_k: int = 0
    mb_user_agent: str = (
        "yt-music-analyzer/1.0 (local personal project; contact: example@example.com)"
    )
    mb_enabled: bool = True
    lyrics_limit: int = 200
    # порог доли вокала: YAMNet даёт низкие абсолютные вероятности
    # («Singing» ~0.004–0.1 у вокальных треков), инструменталы ~0–0.005
    lyrics_min_vocal: float = 0.3
    audio_cookies_from_browser: str = "chrome"
    audio_cookies_keyring: str = "basictext"

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

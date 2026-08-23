from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    youtube_api_key: str = ""
    youtube_daily_quota: int = 10000
    timezone: str = "Europe/Moscow"
    data_dir: Path = Path("data")
    audio_analysis_limit: int = 5
    audio_delete_after: bool = False
    cluster_k: int = 0
    mb_user_agent: str = (
        "yt-music-analyzer/1.0 (local personal project; contact: example@example.com)"
    )
    mb_enabled: bool = True
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
        for p in (self.data_dir, self.audio_dir, self.uploads_dir):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()

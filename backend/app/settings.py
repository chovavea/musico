from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://musico:musico@127.0.0.1:5432/musico",
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="DB_MAX_OVERFLOW")
    enable_media_resolver: bool = Field(default=False, alias="ENABLE_MEDIA_RESOLVER")
    staleness_multiplier: int = Field(default=2, alias="STALENESS_MULTIPLIER")
    preview_min_interval_sec: float = Field(default=0.1, alias="PREVIEW_MIN_INTERVAL_SEC")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    boards_yaml: Path = Field(default=Path("/app/configs/boards.yaml"), alias="BOARDS_YAML")
    http_timeout_sec: float = Field(default=15.0, alias="HTTP_TIMEOUT_SEC")
    api_token: str = Field(default="", alias="API_TOKEN")
    latest_cache_ttl_sec: int = Field(default=45, alias="LATEST_CACHE_TTL_SEC")
    music_library_dir: Path = Field(default=Path("/app/data/music"), alias="MUSIC_LIBRARY_DIR")
    download_source_config: Path = Field(
        default=Path("/app/configs/download_sources.yaml"), alias="DOWNLOAD_SOURCE_CONFIG"
    )
    download_source_dirs: str = Field(default="", alias="DOWNLOAD_SOURCE_DIRS")
    download_max_retries: int = Field(default=3, alias="DOWNLOAD_MAX_RETRIES")
    download_timeout_sec: float = Field(default=300.0, alias="DOWNLOAD_TIMEOUT_SEC")
    download_max_file_size: int = Field(default=2 * 1024 * 1024 * 1024, alias="DOWNLOAD_MAX_FILE_SIZE")
    download_poll_sec: float = Field(default=1.0, alias="DOWNLOAD_POLL_SEC")
    download_lease_sec: int = Field(default=60, alias="DOWNLOAD_LEASE_SEC")

    @property
    def download_roots(self) -> list[Path]:
        configured = [
            Path(item.strip()) for item in self.download_source_dirs.split(",") if item.strip()
        ]
        builtin = Path(__file__).resolve().parent / "download_sources"
        return configured + ([builtin] if builtin not in configured else [])

    @property
    def sync_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql+asyncpg://"):
            return "postgresql+psycopg://" + url.removeprefix("postgresql+asyncpg://")
        if url.startswith("postgresql+psycopg://"):
            return url
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()

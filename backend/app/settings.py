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
    latest_cache_ttl_sec: int = Field(default=45, alias="LATEST_CACHE_TTL_SEC")

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

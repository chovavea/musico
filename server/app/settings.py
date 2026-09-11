import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://musico@127.0.0.1:5432/musico",
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="DB_MAX_OVERFLOW")
    enable_media_resolver: bool = Field(default=False, alias="ENABLE_MEDIA_RESOLVER")
    staleness_multiplier: int = Field(default=2, alias="STALENESS_MULTIPLIER")
    preview_min_interval_sec: float = Field(default=0.1, alias="PREVIEW_MIN_INTERVAL_SEC")
    preview_cross_platform: bool = Field(default=True, alias="PREVIEW_CROSS_PLATFORM")
    preview_match_min_score: float = Field(default=0.94, alias="PREVIEW_MATCH_MIN_SCORE")
    preview_max_candidates: int = Field(default=2, alias="PREVIEW_MAX_CANDIDATES")
    # One budget for the whole cross-platform attempt, including a late audio open.
    # Search and parse calls are not capped individually, so this is the only limit
    # that can end an attempt early.
    preview_deadline_sec: float = Field(default=60.0, alias="PREVIEW_DEADLINE_SEC")
    # Ceiling for a single upstream call (search, preview URL parse, opening the
    # stream). Generous on purpose: a slow answer is still a usable answer.
    preview_call_timeout_sec: float = Field(default=60.0, alias="PREVIEW_CALL_TIMEOUT_SEC")
    preview_negative_ttl_sec: int = Field(default=180, alias="PREVIEW_NEGATIVE_TTL_SEC")
    preview_positive_ttl_sec: int = Field(default=600, alias="PREVIEW_POSITIVE_TTL_SEC")
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
    download_max_file_size: int = Field(
        default=2 * 1024 * 1024 * 1024, alias="DOWNLOAD_MAX_FILE_SIZE"
    )
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


def export_env_file(path: Path | None = None) -> None:
    """Copy ``.env`` entries into ``os.environ`` for plugin-level lookups.

    pydantic-settings loads ``.env`` into the Settings object only, but the
    download sources resolve their addresses through ``os.environ`` so real
    hosts can stay out of the repository.  Existing variables always win.
    """
    candidates = [path] if path is not None else [Path(".env"), _REPO_ROOT / ".env"]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        for raw_line in resolved.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().removeprefix("export ").strip()
            if not key:
                continue
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


@lru_cache
def get_settings() -> Settings:
    return Settings()

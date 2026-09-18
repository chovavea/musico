import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Path defaults are anchored at the repository root: that is ``/app`` inside the
# image (``/app/server/app/settings.py``) and the checkout on a laptop.  The old
# hard-coded ``/app/...`` defaults made a plain local
# ``uvicorn app.main:create_app`` die on ``mkdir /app/data/music``.
_REPO_CONFIGS = _REPO_ROOT / "configs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(default="", alias="DATABASE_URL")
    # Used to assemble ``DATABASE_URL`` when it is not given directly, so the
    # password can arrive as a file (``DATABASE_PASSWORD_FILE``) instead of an
    # environment variable — the convention the official images use too.
    database_host: str = Field(default="127.0.0.1", alias="DATABASE_HOST")
    database_port: int = Field(default=5432, alias="DATABASE_PORT")
    database_user: str = Field(default="musico", alias="DATABASE_USER")
    database_name: str = Field(default="musico", alias="DATABASE_NAME")
    database_password: str = Field(default="", alias="DATABASE_PASSWORD")
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="DB_MAX_OVERFLOW")
    enable_media_resolver: bool = Field(default=False, alias="ENABLE_MEDIA_RESOLVER")
    staleness_multiplier: int = Field(default=2, alias="STALENESS_MULTIPLIER")
    preview_min_interval_sec: float = Field(default=0.1, alias="PREVIEW_MIN_INTERVAL_SEC")
    preview_cross_platform: bool = Field(default=True, alias="PREVIEW_CROSS_PLATFORM")
    preview_match_min_score: float = Field(default=0.9, alias="PREVIEW_MATCH_MIN_SCORE")
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
    preview_adaptive_order: bool = Field(default=True, alias="PREVIEW_ADAPTIVE_ORDER")
    preview_explore_weight: float = Field(
        default=0.08, ge=0.0, le=1.0, alias="PREVIEW_EXPLORE_WEIGHT"
    )
    preview_decay_half_life_sec: float = Field(
        default=259_200.0, gt=0.0, alias="PREVIEW_DECAY_HALF_LIFE_SEC"
    )
    preview_hedge_enabled: bool = Field(default=True, alias="PREVIEW_HEDGE_ENABLED")
    preview_hedge_min_delay_sec: float = Field(
        default=0.4, gt=0.0, alias="PREVIEW_HEDGE_MIN_DELAY_SEC"
    )
    preview_hedge_max_delay_sec: float = Field(
        default=1.5, gt=0.0, alias="PREVIEW_HEDGE_MAX_DELAY_SEC"
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    boards_yaml: Path = Field(default=_REPO_CONFIGS / "boards.yaml", alias="BOARDS_YAML")
    http_timeout_sec: float = Field(default=15.0, alias="HTTP_TIMEOUT_SEC")
    api_token: str = Field(default="", alias="API_TOKEN")
    latest_cache_ttl_sec: int = Field(default=45, alias="LATEST_CACHE_TTL_SEC")
    music_library_dir: Path = Field(
        default=_REPO_ROOT / "data" / "music", alias="MUSIC_LIBRARY_DIR"
    )
    download_source_config: Path = Field(
        default=_REPO_CONFIGS / "download_sources.yaml", alias="DOWNLOAD_SOURCE_CONFIG"
    )
    download_source_dirs: str = Field(default="", alias="DOWNLOAD_SOURCE_DIRS")
    download_max_retries: int = Field(default=3, alias="DOWNLOAD_MAX_RETRIES")
    download_timeout_sec: float = Field(default=300.0, alias="DOWNLOAD_TIMEOUT_SEC")
    download_max_file_size: int = Field(
        default=2 * 1024 * 1024 * 1024, alias="DOWNLOAD_MAX_FILE_SIZE"
    )
    download_poll_sec: float = Field(default=1.0, alias="DOWNLOAD_POLL_SEC")
    download_lease_sec: int = Field(default=60, alias="DOWNLOAD_LEASE_SEC")
    # Link-out fallback: when every download source fails, the browser is sent to
    # a Quark share page and the user finishes the transfer there.  The site
    # address never enters the repository, so it lives in the untracked .env.
    fallback_base_url: str = Field(default="", alias="MUSICO_FALLBACK_BASE_URL")
    fallback_extra_hosts: str = Field(default="", alias="MUSICO_FALLBACK_EXTRA_HOSTS")
    fallback_timeout_sec: float = Field(default=15.0, alias="FALLBACK_TIMEOUT_SEC")
    fallback_positive_ttl_sec: int = Field(default=604800, alias="FALLBACK_POSITIVE_TTL_SEC")
    fallback_negative_ttl_sec: int = Field(default=300, alias="FALLBACK_NEGATIVE_TTL_SEC")
    fallback_event_limit: int = Field(default=20, alias="FALLBACK_EVENT_LIMIT")
    listen_flmp3_base_url: str = Field(default="", alias="MUSICO_LISTEN_FLMP3_BASE_URL")
    listen_flmp3_extra_hosts: str = Field(default="", alias="MUSICO_LISTEN_FLMP3_EXTRA_HOSTS")
    listen_gequbao_base_url: str = Field(default="", alias="MUSICO_LISTEN_GEQUBAO_BASE_URL")
    listen_gequbao_extra_hosts: str = Field(default="", alias="MUSICO_LISTEN_GEQUBAO_EXTRA_HOSTS")

    @model_validator(mode="after")
    def _fill_database_url(self) -> "Settings":
        if self.database_url:
            return self
        credentials = self.database_user
        if self.database_password:
            credentials += f":{quote(self.database_password, safe='')}"
        self.database_url = (
            f"postgresql+psycopg://{credentials}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )
        return self

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
    _ensure_local_database_url()


def _ensure_local_database_url() -> None:
    """Compose DATABASE_URL from POSTGRES_* when nothing else names a database.

    The repository's own stack hands the app ``POSTGRES_*``, while a deployment
    that keeps the password in a secret file hands over ``DATABASE_HOST`` /
    ``DATABASE_USER`` / ``DATABASE_NAME`` instead.  The two must not fight: an
    explicit ``DATABASE_URL`` or ``DATABASE_HOST`` always wins, so injecting
    ``POSTGRES_*`` into a container can never silently point the app (and alembic,
    which prefers ``os.environ["DATABASE_URL"]``) at 127.0.0.1.
    """
    if os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_HOST"):
        return
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    db = os.environ.get("POSTGRES_DB")
    if not user or not db:
        return
    from urllib.parse import quote

    auth = quote(user, safe="")
    if password:
        auth = f"{auth}:{quote(password, safe='')}"
    os.environ["DATABASE_URL"] = f"postgresql+psycopg://{auth}@127.0.0.1:5432/{quote(db, safe='')}"


def _setting_aliases() -> set[str]:
    return {field.alias for field in Settings.model_fields.values() if field.alias}


def apply_file_env() -> None:
    """Resolve ``<ALIAS>_FILE`` into ``<ALIAS>`` for known settings.

    Docker's official images accept ``FOO_FILE`` as a pointer to a file holding
    the value of ``FOO``.  The same convention here keeps secrets out of the
    container environment (and out of ``docker inspect``): an explicit
    non-empty value always wins, and an unreadable or empty file is a hard
    error rather than a silent fallback to a default.

    An *empty* variable counts as absent, which is what lets compose pass
    ``DATABASE_PASSWORD=""`` while a deployment keeps using
    ``DATABASE_PASSWORD_FILE``.
    """
    for alias in _setting_aliases():
        path = os.environ.get(f"{alias}_FILE")
        if not path or os.environ.get(alias):
            continue
        try:
            value = Path(path).read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise RuntimeError(f"{alias}_FILE is not readable: {path}") from exc
        if not value:
            raise RuntimeError(f"{alias}_FILE is empty: {path}")
        os.environ[alias] = value


@lru_cache
def get_settings() -> Settings:
    apply_file_env()
    return Settings()

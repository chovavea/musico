from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import structlog
import yaml
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.adapters.download_worker import DownloadWorker
from app.adapters.http.middleware import ApiTokenMiddleware, RequestIdMiddleware
from app.adapters.http.routes import build_router
from app.adapters.persistence.database import make_engine, make_session_factory
from app.adapters.persistence.repository import ChartRepository
from app.adapters.scheduler.jobs import ChartScheduler
from app.download_sources.registry import load_download_sources
from app.logging import configure_logging
from app.plugins._registry import load_registry
from app.services.boards_config import BoardsConfigError, load_raw_boards, parse_board_specs
from app.services.collect import CollectService
from app.services.downloads import DownloadService
from app.services.preview_telemetry import prewarm as prewarm_preview_stats
from app.settings import Settings, get_settings

log = structlog.get_logger(__name__)


class SPAStaticFiles(StaticFiles):
    """Serve the Vue entrypoint for client-side routes while preserving asset 404s."""

    async def get_response(self, path: str, scope: dict) -> object:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            normalized_path = path.replace("\\", "/").lstrip("/")
            if (
                exc.status_code == 404
                and scope.get("method") in {"GET", "HEAD"}
                and not Path(path).suffix
                and normalized_path not in {"api", "api/"}
                and not normalized_path.startswith("api/")
            ):
                return await super().get_response("index.html", scope)
            raise


def _resolve_boards_path(settings: Settings) -> Path:
    path = settings.boards_yaml
    if path.is_file():
        return path
    fallback = Path(__file__).resolve().parents[2] / "configs" / "boards.yaml"
    if fallback.is_file():
        return fallback
    return path


def _resolve_download_config(settings: Settings) -> dict[str, object]:
    path = settings.download_source_config
    if not path.is_file():
        fallback = Path(__file__).resolve().parents[2] / "configs" / "download_sources.yaml"
        path = fallback if fallback.is_file() else path
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _run_alembic(settings: Settings) -> None:
    from alembic import command
    from alembic.config import Config

    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option(
        "sqlalchemy.url",
        settings.sync_database_url.replace("%", "%%"),
    )
    command.upgrade(cfg, "head")


async def _wait_for_database(engine: AsyncEngine, attempts: int = 30) -> None:
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except (OSError, TimeoutError, SQLAlchemyError) as exc:
            last = exc
            log.warning("database_wait", attempt=attempt, error=str(exc))
            await asyncio.sleep(1)
    raise RuntimeError("database not ready") from last


def create_app(
    settings: Settings | None = None,
    *,
    start_scheduler: bool = True,
    run_migrations: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    boards_path = _resolve_boards_path(settings)
    try:
        raw = load_raw_boards(boards_path)
        specs = parse_board_specs(raw)
    except BoardsConfigError as exc:
        log.error("boards_yaml_invalid", error=str(exc))
        raise SystemExit(1) from exc

    engine = make_engine(settings)
    session_factory = make_session_factory(engine)
    user_agent = "musico/0.1 (+self-hosted charts)"
    timeout = httpx.Timeout(settings.http_timeout_sec)
    client = httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": user_agent},
        follow_redirects=True,
    )
    # Long-lived media streams get dedicated clients with redirects disabled:
    # every hop is re-validated manually, and a stalled CDN cannot starve the
    # connection pool used by chart collection / health checks.
    preview_client = httpx.AsyncClient(
        # Preview calls must not be cut short by the generic HTTP timeout: a slow
        # upstream still plays, so every phase gets the full per-call ceiling.
        timeout=httpx.Timeout(settings.preview_call_timeout_sec),
        headers={"User-Agent": user_agent},
        follow_redirects=False,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )
    download_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_sec, read=settings.download_timeout_sec),
        headers={"User-Agent": user_agent},
        follow_redirects=False,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )
    registry = load_registry(client)
    download_sources = load_download_sources(
        client,
        roots=settings.download_roots,
        config=_resolve_download_config(settings),
    )
    unknown = [spec.platform for spec in specs if spec.platform not in registry.plugins]
    if unknown:
        log.error("unknown_platforms", platforms=unknown)
        raise SystemExit(1)
    if settings.enable_media_resolver and not registry.has_media_port():
        log.error("media_resolver_enabled_without_implementation")
        raise SystemExit(1)

    collect = CollectService(registry, session_factory, settings, cache={})
    scheduler = ChartScheduler(collect, specs) if start_scheduler else None
    download_service = DownloadService(session_factory, settings)
    download_worker = DownloadWorker(session_factory, download_client, download_sources, settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await _wait_for_database(engine)
        if run_migrations:
            _run_alembic(settings)
            # Alembic re-applies alembic.ini logging via fileConfig; restore the
            # application's structured logging before serving requests.
            configure_logging(settings.log_level)
        async with session_factory() as session:
            await ChartRepository(session).upsert_catalog(specs, registry.platform_names())
            await session.commit()
        await prewarm_preview_stats(session_factory)
        settings.music_library_dir.mkdir(parents=True, exist_ok=True)
        if scheduler is not None:
            scheduler.start()
        download_worker.start()
        yield
        await download_worker.shutdown()
        if scheduler is not None:
            scheduler.shutdown()
        await client.aclose()
        await preview_client.aclose()
        await download_client.aclose()
        await engine.dispose()

    app = FastAPI(title="musico", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(ApiTokenMiddleware, api_token=settings.api_token)
    app.include_router(build_router())
    app.state.settings = settings
    app.state.board_specs = specs
    app.state.registry = registry
    app.state.download_sources = download_sources
    app.state.download_service = download_service
    app.state.download_worker = download_worker
    app.state.session_factory = session_factory
    app.state.latest_cache = collect.latest_cache
    app.state.collect = collect
    app.state.http_client = client
    app.state.preview_client = preview_client

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="frontend")

    return app

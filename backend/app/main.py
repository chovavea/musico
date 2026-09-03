from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.http.middleware import RequestIdMiddleware
from app.adapters.http.routes import build_router
from app.adapters.persistence.database import make_engine, make_session_factory
from app.adapters.persistence.repository import ChartRepository
from app.adapters.scheduler.jobs import ChartScheduler
from app.logging import configure_logging
from app.plugins._registry import load_registry
from app.services.boards_config import BoardsConfigError, load_raw_boards, parse_board_specs
from app.services.collect import CollectService
from app.settings import Settings, get_settings

log = structlog.get_logger(__name__)


def _resolve_boards_path(settings: Settings) -> Path:
    path = settings.boards_yaml
    if path.is_file():
        return path
    fallback = Path(__file__).resolve().parents[2] / "configs" / "boards.yaml"
    if fallback.is_file():
        return fallback
    return path


def _run_alembic(settings: Settings) -> None:
    from alembic import command
    from alembic.config import Config

    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", settings.sync_database_url)
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
    timeout = httpx.Timeout(settings.http_timeout_sec)
    client = httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "musico/0.1 (+self-hosted charts)"},
        follow_redirects=True,
    )
    registry = load_registry(client)
    unknown = [spec.platform for spec in specs if spec.platform not in registry.plugins]
    if unknown:
        log.error("unknown_platforms", platforms=unknown)
        raise SystemExit(1)
    if settings.enable_media_resolver and not registry.has_media_port():
        log.error("media_resolver_enabled_without_implementation")
        raise SystemExit(1)

    collect = CollectService(registry, session_factory, settings, cache={})
    scheduler = ChartScheduler(collect, specs) if start_scheduler else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await _wait_for_database(engine)
        if run_migrations:
            _run_alembic(settings)
        async with session_factory() as session:
            await ChartRepository(session).upsert_catalog(specs, registry.platform_names())
            await session.commit()
        if scheduler is not None:
            scheduler.start()
        yield
        if scheduler is not None:
            scheduler.shutdown()
        await client.aclose()
        await engine.dispose()

    app = FastAPI(title="musico", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(build_router())
    app.state.settings = settings
    app.state.board_specs = specs
    app.state.registry = registry
    app.state.session_factory = session_factory
    app.state.latest_cache = collect.latest_cache
    app.state.collect = collect
    app.state.http_client = client

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app

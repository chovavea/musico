from __future__ import annotations

import time
from typing import Any

import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence.repository import ChartRepository
from app.domain.models import BoardSpec, RawRankItem
from app.plugins._registry import PluginRegistry
from app.settings import Settings

log = structlog.get_logger(__name__)


class CollectService:
    def __init__(
        self,
        registry: PluginRegistry,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        cache: dict[str, Any] | None = None,
    ) -> None:
        self._registry = registry
        self._session_factory = session_factory
        self._settings = settings
        self.latest_cache = cache if cache is not None else {}

    async def collect_board(self, spec: BoardSpec) -> None:
        started = time.perf_counter()
        log.info("collect_start", platform=spec.platform, board_id=spec.id)
        extra_issues = self._registry.extra_ok(spec)
        if extra_issues:
            await self._health(
                spec.id,
                ok=False,
                latency_ms=0,
                item_count=None,
                error="; ".join(extra_issues),
            )
            log.warning("collect_skip_extra", board_id=spec.id, errors=extra_issues)
            return
        record = self._registry.get(spec.platform)
        if record is None or record.chart is None:
            await self._health(
                spec.id, ok=False, latency_ms=0, item_count=None, error="chart plugin missing"
            )
            return
        try:
            raw_items = await record.chart.fetch_board(spec)
            items = _validate_items(raw_items, spec.id)
            if not items:
                raise ValueError("no valid rank items")
            # Official preview URLs expire; resolve on play via /preview/.../stream.
            async with self._session_factory() as session:
                repo = ChartRepository(session)
                await repo.persist_snapshot(spec, items)
                latency_ms = int((time.perf_counter() - started) * 1000)
                await repo.record_health(
                    spec.id, ok=True, latency_ms=latency_ms, item_count=len(items), error=None
                )
                await session.commit()
            self.latest_cache.pop(f"latest:{spec.id}", None)
            log.info(
                "collect_end",
                platform=spec.platform,
                board_id=spec.id,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                item_count=len(items),
            )
        except Exception as exc:
            log.exception("collect_failed", platform=spec.platform, board_id=spec.id)
            await self._health(
                spec.id,
                ok=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                item_count=None,
                error=str(exc),
            )

    async def _health(
        self,
        board_id: str,
        *,
        ok: bool,
        latency_ms: int,
        item_count: int | None,
        error: str | None,
    ) -> None:
        try:
            async with self._session_factory() as session:
                repo = ChartRepository(session)
                await repo.record_health(
                    board_id, ok=ok, latency_ms=latency_ms, item_count=item_count, error=error
                )
                await session.commit()
        except Exception:
            log.exception("health_write_failed", board_id=board_id)


def _validate_items(raw_items: list[RawRankItem], board_id: str) -> list[RawRankItem]:
    valid: list[RawRankItem] = []
    for item in raw_items:
        try:
            valid.append(RawRankItem.model_validate(item.model_dump()))
        except ValidationError:
            log.warning("drop_invalid_item", board_id=board_id)
    return valid

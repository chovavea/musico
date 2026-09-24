from __future__ import annotations

import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.domain.models import BoardSpec
from app.services.collect import CollectService

log = structlog.get_logger(__name__)


class ChartScheduler:
    def __init__(self, collect: CollectService, specs: list[BoardSpec]) -> None:
        self._collect = collect
        self._specs = [spec for spec in specs if spec.enabled]
        self._locks: dict[str, asyncio.Lock] = {spec.id: asyncio.Lock() for spec in self._specs}
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        for spec in self._specs:
            self._scheduler.add_job(
                self._run_one,
                "interval",
                seconds=spec.interval_sec,
                id=spec.id,
                args=[spec],
                kwargs={"preserve_movement": False},
                max_instances=1,
                coalesce=True,
            )
        self._scheduler.start()
        for spec in self._specs:
            # A process start is not an hourly refresh. Keep the movement
            # already stored, even when the last snapshot is from yesterday.
            self._scheduler.add_job(
                self._run_one,
                id=f"{spec.id}_once",
                args=[spec],
                kwargs={"preserve_movement": True},
            )

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def _run_one(self, spec: BoardSpec, *, preserve_movement: bool = False) -> None:
        lock = self._locks[spec.id]
        if lock.locked():
            log.warning("collect_skip_locked", board_id=spec.id)
            return
        async with lock:
            await self._collect.collect_board(spec, preserve_movement=preserve_movement)

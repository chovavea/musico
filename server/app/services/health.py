from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence.repository import ChartRepository
from app.domain.models import BoardSpec
from app.settings import Settings

HealthStatus = Literal["starting", "ready", "degraded"]


def compute_staleness(
    updated_at: datetime,
    interval_sec: int,
    multiplier: int,
    *,
    now: datetime | None = None,
) -> Literal["fresh", "stale"]:
    current = now or datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age = (current - updated_at).total_seconds()
    if age <= interval_sec * multiplier:
        return "fresh"
    return "stale"


async def build_health(
    session_factory: async_sessionmaker[AsyncSession],
    specs: list[BoardSpec],
    settings: Settings,
) -> dict[str, Any]:
    enabled = [spec for spec in specs if spec.enabled]
    async with session_factory() as session:
        repo = ChartRepository(session)
        rows = await repo.list_health()
        success = await repo.boards_with_success()
    by_id = {row.board_id: row for row in rows}
    sources: list[dict[str, Any]] = []
    any_fail = False
    for spec in enabled:
        row = by_id.get(spec.id)
        consecutive = int(row.consecutive_failures) if row is not None else 0
        if consecutive > 0:
            any_fail = True
        sources.append(
            {
                "board_id": spec.id,
                "platform": spec.platform,
                "name": spec.name,
                "last_success_at": row.last_success_at.isoformat()
                if row is not None and row.last_success_at
                else None,
                "last_error": row.last_error if row is not None else None,
                "consecutive_failures": consecutive,
                "last_latency_ms": row.last_latency_ms if row is not None else None,
                "last_item_count": row.last_item_count if row is not None else None,
            }
        )
    missing = [spec.id for spec in enabled if spec.id not in success]
    status: HealthStatus
    if missing:
        status = "starting"
    elif any_fail:
        status = "degraded"
    else:
        status = "ready"
    return {
        "status": status,
        "staleness_multiplier": settings.staleness_multiplier,
        "sources": sources,
    }

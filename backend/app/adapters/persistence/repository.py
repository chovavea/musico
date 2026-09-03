from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import (
    BoardLatestRow,
    BoardRow,
    CatalogChartOrderRow,
    PlatformRow,
    PlatformSongRow,
    ProviderHealthRow,
    RankEntryRow,
    RankSnapshotRow,
)
from app.domain.models import BoardSpec, RawRankItem
from app.domain.normalize import normalized_score


def _now() -> datetime:
    return datetime.now(UTC)


class ChartRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_catalog(self, specs: list[BoardSpec], platform_names: dict[str, str]) -> None:
        for platform_id, name in platform_names.items():
            existing = await self._session.get(PlatformRow, platform_id)
            if existing is None:
                self._session.add(PlatformRow(id=platform_id, name=name))
            else:
                existing.name = name
        next_order = await self._next_sort_order()
        added = 0
        for index, spec in enumerate(specs):
            row = await self._session.get(BoardRow, spec.id)
            if row is None:
                self._session.add(
                    BoardRow(
                        id=spec.id,
                        platform_id=spec.platform,
                        name=spec.name,
                        type=spec.type,
                        enabled=spec.enabled,
                        sort_order=next_order + added * 10,
                    )
                )
                added += 1
            else:
                row.platform_id = spec.platform
                row.name = spec.name
                row.type = spec.type
                row.enabled = spec.enabled
                if row.sort_order == 0:
                    row.sort_order = (index + 1) * 10

    async def persist_snapshot(self, spec: BoardSpec, items: list[RawRankItem]) -> str:
        latest = await self._session.get(BoardLatestRow, spec.id)
        previous_ranks: dict[str, int] = {}
        if latest is not None:
            result = await self._session.execute(
                select(RankEntryRow.platform_song_id, RankEntryRow.rank).where(
                    RankEntryRow.snapshot_id == latest.snapshot_id
                )
            )
            previous_ranks = {str(song_id): int(rank) for song_id, rank in result.all()}

        n = len(items)
        snapshot = RankSnapshotRow(id=str(uuid.uuid4()), board_id=spec.id, fetched_at=_now())
        self._session.add(snapshot)
        await self._session.flush()

        for item in items:
            song_id = await self._upsert_song(spec.platform, item)
            self._session.add(
                RankEntryRow(
                    snapshot_id=snapshot.id,
                    platform_song_id=song_id,
                    rank=item.rank,
                    raw_score=item.raw_score,
                    normalized_score=normalized_score(item.rank, n),
                    previous_rank=previous_ranks.get(song_id),
                    preview_url=item.preview_url or None,
                    preview_quality=item.preview_quality,
                    preview_expire_at=item.preview_expire_at,
                )
            )

        now = _now()
        if latest is None:
            self._session.add(
                BoardLatestRow(board_id=spec.id, snapshot_id=snapshot.id, updated_at=now)
            )
        else:
            latest.snapshot_id = snapshot.id
            latest.updated_at = now
        return snapshot.id

    async def _upsert_song(self, platform: str, item: RawRankItem) -> str:
        result = await self._session.execute(
            select(PlatformSongRow).where(
                PlatformSongRow.platform_id == platform,
                PlatformSongRow.external_id == item.external_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = PlatformSongRow(
                id=str(uuid.uuid4()),
                platform_id=platform,
                external_id=item.external_id,
                title=item.title,
                artist=item.artist,
                cover_url=item.cover_url,
                official_url=item.official_url,
            )
            self._session.add(row)
            await self._session.flush()
            return row.id
        row.title = item.title
        row.artist = item.artist
        row.cover_url = item.cover_url
        row.official_url = item.official_url
        return row.id

    async def record_health(
        self,
        board_id: str,
        *,
        ok: bool,
        latency_ms: int,
        item_count: int | None,
        error: str | None,
    ) -> None:
        row = await self._session.get(ProviderHealthRow, board_id)
        if row is None:
            row = ProviderHealthRow(board_id=board_id, consecutive_failures=0)
            self._session.add(row)
        row.last_latency_ms = latency_ms
        row.last_item_count = item_count
        if ok:
            row.last_success_at = _now()
            row.last_error = None
            row.consecutive_failures = 0
        else:
            row.consecutive_failures = int(row.consecutive_failures) + 1
            row.last_error = (error or "unknown error")[:500]

    async def get_latest_payload(self, board_id: str) -> dict[str, Any] | None:
        latest = await self._session.get(BoardLatestRow, board_id)
        if latest is None:
            return None
        snapshot = await self._session.get(RankSnapshotRow, latest.snapshot_id)
        if snapshot is None:
            return None
        result = await self._session.execute(
            select(RankEntryRow, PlatformSongRow)
            .join(PlatformSongRow, PlatformSongRow.id == RankEntryRow.platform_song_id)
            .where(RankEntryRow.snapshot_id == snapshot.id)
            .order_by(RankEntryRow.rank.asc())
        )
        entries: list[dict[str, Any]] = []
        for entry, song in result.all():
            entries.append(
                {
                    "rank": entry.rank,
                    "previous_rank": entry.previous_rank,
                    "normalized_score": entry.normalized_score,
                    "raw_score": entry.raw_score,
                    "title": song.title,
                    "artist": song.artist,
                    "cover_url": song.cover_url,
                    "official_url": song.official_url,
                    "external_id": song.external_id,
                    "platform": song.platform_id,
                    "preview_url": entry.preview_url,
                    "quality": entry.preview_quality,
                    "expire_at": entry.preview_expire_at.isoformat()
                    if entry.preview_expire_at
                    else None,
                }
            )
        return {
            "board_id": board_id,
            "snapshot_id": snapshot.id,
            "fetched_at": snapshot.fetched_at.isoformat(),
            "updated_at": latest.updated_at.isoformat(),
            "updated_at_dt": latest.updated_at,
            "items": entries,
        }

    async def board_sort_map(self) -> dict[str, int]:
        result = await self._session.execute(select(BoardRow.id, BoardRow.sort_order))
        return {str(board_id): int(sort_order) for board_id, sort_order in result.all()}

    async def move_board(
        self,
        board_id: str,
        direction: str,
        allowed_ids: set[str] | None = None,
    ) -> bool:
        result = await self._session.execute(
            select(BoardRow).order_by(BoardRow.sort_order.asc(), BoardRow.id.asc())
        )
        rows = [
            row
            for row in result.scalars().all()
            if allowed_ids is None or row.id in allowed_ids
        ]
        ids = [row.id for row in rows]
        try:
            index = ids.index(board_id)
        except ValueError:
            return False
        swap = index - 1 if direction == "up" else index + 1
        if swap < 0 or swap >= len(rows):
            return True
        rows[index], rows[swap] = rows[swap], rows[index]
        for order, row in enumerate(rows, start=1):
            row.sort_order = order * 10
        return True

    async def catalog_order_map(self, platform_id: str) -> dict[str, int]:
        result = await self._session.execute(
            select(CatalogChartOrderRow.chart_key, CatalogChartOrderRow.sort_order).where(
                CatalogChartOrderRow.platform_id == platform_id
            )
        )
        return {str(chart_key): int(sort_order) for chart_key, sort_order in result.all()}

    async def replace_catalog_order(self, platform_id: str, keys: list[str]) -> None:
        await self._session.execute(
            delete(CatalogChartOrderRow).where(CatalogChartOrderRow.platform_id == platform_id)
        )
        for order, key in enumerate(keys, start=1):
            self._session.add(
                CatalogChartOrderRow(
                    platform_id=platform_id,
                    chart_key=key,
                    sort_order=order * 10,
                )
            )

    async def move_catalog_chart(
        self,
        platform_id: str,
        chart_key: str,
        direction: str,
        current_keys: list[str],
    ) -> bool:
        keys = list(current_keys)
        try:
            index = keys.index(chart_key)
        except ValueError:
            return False
        swap = index - 1 if direction == "up" else index + 1
        if 0 <= swap < len(keys):
            keys[index], keys[swap] = keys[swap], keys[index]
        await self.replace_catalog_order(platform_id, keys)
        return True

    async def reorder_catalog_chart(
        self,
        platform_id: str,
        chart_key: str,
        before_key: str | None,
        current_keys: list[str],
    ) -> bool:
        from app.services.catalog import insert_chart_before

        keys = insert_chart_before(current_keys, chart_key, before_key)
        if keys is None:
            return False
        await self.replace_catalog_order(platform_id, keys)
        return True

    async def _next_sort_order(self) -> int:
        result = await self._session.execute(select(func.max(BoardRow.sort_order)))
        current = result.scalar_one()
        return (int(current) if current is not None else 0) + 10

    async def list_health(self) -> list[ProviderHealthRow]:
        result = await self._session.execute(select(ProviderHealthRow))
        return list(result.scalars().all())

    async def boards_with_success(self) -> set[str]:
        result = await self._session.execute(
            select(ProviderHealthRow.board_id).where(ProviderHealthRow.last_success_at.is_not(None))
        )
        return {row[0] for row in result.all()}

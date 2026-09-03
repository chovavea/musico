from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.persistence.models import Base
from app.adapters.persistence.repository import ChartRepository
from app.domain.models import BoardSpec, RawRankItem
from app.plugins._registry import PluginRecord, PluginRegistry
from app.services.collect import CollectService
from app.settings import Settings


class _FakeChart:
    def __init__(self, batches: list[list[RawRankItem]]) -> None:
        self._batches = list(batches)

    async def fetch_board(self, board_config: BoardSpec) -> list[RawRankItem]:
        _ = board_config
        return self._batches.pop(0)


def _item(rank: int, external_id: str, title: str) -> RawRankItem:
    return RawRankItem(
        rank=rank,
        external_id=external_id,
        title=title,
        artist="周杰伦",
        official_url=f"https://example.com/{external_id}",
    )


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    spec = BoardSpec(
        id="qq_hot",
        platform="qqmusic",
        name="QQ",
        type="hot",
        interval_sec=1800,
        extra={"top_id": 26},
    )
    async with factory() as session:
        await ChartRepository(session).upsert_catalog([spec], {"qqmusic": "QQ音乐"})
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_previous_rank_in_second_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    spec = BoardSpec(
        id="qq_hot",
        platform="qqmusic",
        name="QQ",
        type="hot",
        interval_sec=1800,
        extra={"top_id": 26},
    )
    chart = _FakeChart(
        [
            [_item(1, "a", "晴天"), _item(2, "b", "七里香")],
            [_item(1, "b", "七里香"), _item(2, "a", "晴天")],
        ]
    )
    registry = PluginRegistry(
        plugins={
            "qqmusic": PluginRecord(
                plugin_id="qqmusic",
                name="QQ音乐",
                capabilities=["chart"],
                config_schema={"required": ["top_id"], "types": {"top_id": "int"}},
                chart=chart,
            )
        }
    )
    settings = Settings()
    service = CollectService(registry, session_factory, settings)
    await service.collect_board(spec)
    await service.collect_board(spec)
    async with session_factory() as session:
        payload = await ChartRepository(session).get_latest_payload("qq_hot")
    assert payload is not None
    by_id = {item["external_id"]: item for item in payload["items"]}
    assert by_id["b"]["rank"] == 1
    assert by_id["b"]["previous_rank"] == 2
    assert by_id["a"]["rank"] == 2
    assert by_id["a"]["previous_rank"] == 1


@pytest.mark.asyncio
async def test_missing_extra_skips_and_records_health(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    spec = BoardSpec(
        id="qq_hot",
        platform="qqmusic",
        name="QQ",
        type="hot",
        interval_sec=1800,
        extra={},
    )
    registry = PluginRegistry(
        plugins={
            "qqmusic": PluginRecord(
                plugin_id="qqmusic",
                name="QQ音乐",
                capabilities=["chart"],
                config_schema={"required": ["top_id"], "types": {"top_id": "int"}},
                chart=_FakeChart([]),
            )
        }
    )
    service = CollectService(registry, session_factory, Settings())
    await service.collect_board(spec)
    async with session_factory() as session:
        rows = await ChartRepository(session).list_health()
    assert rows[0].consecutive_failures == 1
    assert rows[0].last_error is not None
    assert "top_id" in rows[0].last_error

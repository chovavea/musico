from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from app.adapters.persistence.models import Base, BoardLatestRow, PlatformSongRow
from app.adapters.persistence.repository import ChartRepository, _remembered_previous
from app.domain.models import BoardSpec, RawRankItem
from app.plugins._registry import PluginRecord, PluginRegistry
from app.services.collect import CollectService
from app.settings import Settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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


def test_remembered_previous_keeps_a_restart_and_flattens_on_schedule() -> None:
    assert _remembered_previous(None, None, 1, keep_movement=True) is None
    assert _remembered_previous(5, None, 5, keep_movement=True) is None
    assert _remembered_previous(5, None, 5, keep_movement=False) == 5
    assert _remembered_previous(2, 5, 2, keep_movement=True) == 5
    assert _remembered_previous(2, 5, 2, keep_movement=False) == 2
    assert _remembered_previous(2, 5, 1, keep_movement=False) == 2


@pytest.mark.asyncio
async def test_scheduled_recollect_flattens_an_unchanged_rank(
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
    settled = [_item(1, "b", "七里香"), _item(2, "a", "晴天")]
    chart = _FakeChart(
        [
            [_item(1, "a", "晴天"), _item(2, "b", "七里香")],
            settled,
            settled,
            [_item(1, "a", "晴天"), _item(2, "b", "七里香")],
        ]
    )
    service = CollectService(
        PluginRegistry(
            plugins={
                "qqmusic": PluginRecord(
                    plugin_id="qqmusic",
                    name="QQ音乐",
                    capabilities=["chart"],
                    config_schema={"required": ["top_id"], "types": {"top_id": "int"}},
                    chart=chart,
                )
            }
        ),
        session_factory,
        Settings(),
    )
    await service.collect_board(spec)
    await service.collect_board(spec)
    async with session_factory() as session:
        latest = await session.get(BoardLatestRow, spec.id)
        assert latest is not None
        latest.updated_at = datetime.now(UTC) - timedelta(seconds=spec.interval_sec)
        await session.commit()
    await service.collect_board(spec)
    async with session_factory() as session:
        payload = await ChartRepository(session).get_latest_payload("qq_hot")
    assert payload is not None
    by_id = {item["external_id"]: item for item in payload["items"]}
    assert by_id["b"]["previous_rank"] == by_id["b"]["rank"]
    assert by_id["a"]["previous_rank"] == by_id["a"]["rank"]
    await service.collect_board(spec)
    async with session_factory() as session:
        payload = await ChartRepository(session).get_latest_payload("qq_hot")
    assert payload is not None
    moved = {item["external_id"]: item for item in payload["items"]}
    assert moved["a"]["rank"] == 1
    assert moved["a"]["previous_rank"] == 2
    assert moved["b"]["rank"] == 2
    assert moved["b"]["previous_rank"] == 1


@pytest.mark.asyncio
async def test_unchanged_rank_keeps_the_stored_movement(
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
    service = CollectService(registry, session_factory, Settings())
    await service.collect_board(spec)
    await service.collect_board(spec)
    async with session_factory() as session:
        latest = await session.get(BoardLatestRow, spec.id)
        assert latest is not None
        latest.updated_at = datetime.now(UTC) - timedelta(hours=12)
        await session.commit()
    await service.collect_board(spec, preserve_movement=True)
    async with session_factory() as session:
        payload = await ChartRepository(session).get_latest_payload("qq_hot")
    assert payload is not None
    by_id = {item["external_id"]: item for item in payload["items"]}
    assert by_id["b"]["rank"] == 1
    assert by_id["b"]["previous_rank"] == 2
    assert by_id["a"]["rank"] == 2
    assert by_id["a"]["previous_rank"] == 1


@pytest.mark.asyncio
async def test_same_platform_song_is_updated_not_duplicated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = RawRankItem(
        rank=1,
        external_id="shared",
        title="晴天",
        artist="周杰伦",
        duration_ms=269000,
        official_url="https://example.com/shared",
    )
    second = RawRankItem(
        rank=3,
        external_id="shared",
        title="晴天 (Live)",
        artist="周杰伦",
        official_url="https://example.com/shared-live",
    )
    async with session_factory() as session:
        repo = ChartRepository(session)
        first_id = await repo._upsert_song("qqmusic", first)
        second_id = await repo._upsert_song("qqmusic", second)
        await session.commit()
    assert first_id == second_id
    async with session_factory() as session:
        row = await session.get(PlatformSongRow, first_id)
    assert row is not None
    assert row.title == "晴天 (Live)"
    assert row.duration_ms == 269000
    assert row.official_url == "https://example.com/shared-live"


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

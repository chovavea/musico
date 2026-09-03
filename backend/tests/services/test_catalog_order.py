from __future__ import annotations

import pytest
import pytest_asyncio
from app.adapters.persistence.models import Base, PlatformRow
from app.adapters.persistence.repository import ChartRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(PlatformRow(id="qqmusic", name="QQ音乐"))
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_move_catalog_chart_swaps_and_persists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    keys = ["4", "26", "27", "5"]
    async with session_factory() as session:
        repo = ChartRepository(session)
        assert await repo.move_catalog_chart("qqmusic", "26", "up", keys)
        await session.commit()
        order = await repo.catalog_order_map("qqmusic")
    assert sorted(order, key=order.get) == ["26", "4", "27", "5"]

    async with session_factory() as session:
        repo = ChartRepository(session)
        persisted = await repo.catalog_order_map("qqmusic")
        assert persisted == order
        current = sorted(persisted, key=persisted.get)
        assert await repo.move_catalog_chart("qqmusic", "26", "up", current) is True
        unchanged = await repo.catalog_order_map("qqmusic")
        assert unchanged == persisted


@pytest.mark.asyncio
async def test_move_unknown_chart_returns_false(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repo = ChartRepository(session)
        assert await repo.move_catalog_chart("qqmusic", "999", "down", ["4", "26"]) is False


@pytest.mark.asyncio
async def test_reorder_catalog_chart_inserts_before(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    keys = ["4", "26", "27", "5"]
    async with session_factory() as session:
        repo = ChartRepository(session)
        assert await repo.reorder_catalog_chart("qqmusic", "5", "26", keys)
        await session.commit()
        order = await repo.catalog_order_map("qqmusic")
    assert sorted(order, key=order.get) == ["4", "5", "26", "27"]

    async with session_factory() as session:
        repo = ChartRepository(session)
        current = sorted(
            (await repo.catalog_order_map("qqmusic")).items(),
            key=lambda item: item[1],
        )
        current_keys = [key for key, _ in current]
        assert await repo.reorder_catalog_chart("qqmusic", "4", None, current_keys)
        await session.commit()
        order = await repo.catalog_order_map("qqmusic")
    assert sorted(order, key=order.get) == ["5", "26", "27", "4"]

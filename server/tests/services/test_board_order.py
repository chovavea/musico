from __future__ import annotations

import pytest
import pytest_asyncio
from app.adapters.persistence.models import Base
from app.adapters.persistence.repository import ChartRepository
from app.domain.models import BoardSpec
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _spec(board_id: str, platform: str, name: str) -> BoardSpec:
    extra = {"top_id": 26} if platform == "qqmusic" else {"playlist_id": "1"}
    return BoardSpec(
        id=board_id,
        platform=platform,
        name=name,
        type="hot",
        interval_sec=1800,
        extra=extra,
    )


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specs = [
        _spec("qq_hot", "qqmusic", "QQ热歌"),
        _spec("netease_hot", "netease", "网易热歌"),
    ]
    async with factory() as session:
        await ChartRepository(session).upsert_catalog(
            specs,
            {"qqmusic": "QQ音乐", "netease": "网易云"},
        )
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_move_board_swaps_and_persists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repo = ChartRepository(session)
        assert await repo.move_board("qq_hot", "down")
        await session.commit()
        order = await repo.board_sort_map()
    assert order["netease_hot"] < order["qq_hot"]

    async with session_factory() as session:
        repo = ChartRepository(session)
        persisted = await repo.board_sort_map()
        assert persisted["netease_hot"] < persisted["qq_hot"]
        assert await repo.move_board("qq_hot", "down") is True
        unchanged = await repo.board_sort_map()
        assert unchanged == persisted

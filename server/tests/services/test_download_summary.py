from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.adapters.persistence.library_repository import LibraryRepository
from app.adapters.persistence.models import DownloadTaskRow, LibraryBase, LibraryTrackRow
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _track(track_id: str, title: str, when: datetime) -> LibraryTrackRow:
    return LibraryTrackRow(
        id=track_id,
        identity_key=track_id,
        title=title,
        artist="歌手",
        normalized_title=title,
        normalized_artist="歌手",
        created_at=when,
        updated_at=when,
    )


async def test_summary_active_follows_the_download_not_an_older_retry() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={"schema_translate_map": {"musico_library": None}},
    )
    earlier = datetime(2026, 10, 10, tzinfo=UTC)
    later = earlier + timedelta(minutes=1)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(LibraryBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add_all(
                [
                    _track("track-old", "旧歌", earlier),
                    _track("track-new", "新歌", later),
                    DownloadTaskRow(
                        id="older",
                        idempotency_key="older",
                        library_track_id="track-old",
                        status="retrying",
                        bytes_done=40,
                        bytes_total=100,
                        next_retry_at=later + timedelta(seconds=30),
                        created_at=earlier,
                    ),
                    DownloadTaskRow(
                        id="newer",
                        idempotency_key="newer",
                        library_track_id="track-new",
                        status="downloading",
                        bytes_done=65,
                        bytes_total=100,
                        heartbeat_at=later,
                        created_at=later,
                    ),
                ]
            )
            await session.commit()
        async with factory() as session:
            payload = await LibraryRepository(session).summary()
        assert payload["active"]["id"] == "newer"
        assert payload["active"]["status"] == "downloading"
        assert payload["active"]["progress"] == 0.65
        assert payload["counts"] == {"retrying": 1, "downloading": 1}
    finally:
        await engine.dispose()


async def test_summary_active_stays_on_a_retry_when_nothing_is_downloading() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={"schema_translate_map": {"musico_library": None}},
    )
    earlier = datetime(2026, 10, 10, tzinfo=UTC)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(LibraryBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add_all(
                [
                    _track("track-old", "旧歌", earlier),
                    DownloadTaskRow(
                        id="older",
                        idempotency_key="older",
                        library_track_id="track-old",
                        status="retrying",
                        bytes_done=40,
                        bytes_total=100,
                        next_retry_at=earlier + timedelta(seconds=30),
                        created_at=earlier,
                    ),
                ]
            )
            await session.commit()
        async with factory() as session:
            payload = await LibraryRepository(session).summary()
        assert payload["active"]["id"] == "older"
        assert payload["active"]["status"] == "retrying"
        assert payload["active"]["progress"] == 0.4
    finally:
        await engine.dispose()

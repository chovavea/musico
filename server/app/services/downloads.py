from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence.library_repository import LibraryRepository, task_idempotency_key
from app.domain.models import (
    ALLOWED_DOWNLOAD_FORMATS,
    AudioQuality,
    TrackRef,
    is_allowed_download_format,
)
from app.settings import Settings


class DownloadService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def request(
        self, track: TrackRef, requested_quality: AudioQuality | None = None
    ) -> dict[str, Any]:
        if requested_quality is not None and not is_allowed_download_format(
            requested_quality.format
        ):
            allowed = ", ".join(ALLOWED_DOWNLOAD_FORMATS)
            raise ValueError(f"requested download format must be one of: {allowed}")
        key = task_idempotency_key(track, requested_quality)
        async with self._session_factory() as session:
            repo = LibraryRepository(session)
            library_track = await repo.find_or_create_track(track)
            asset = await repo.get_ready_asset(library_track.id, requested_quality)
            if asset is not None:
                path = self._asset_path(asset.relative_path)
                if path.is_file():
                    await session.commit()
                    return {"state": "ready", "asset": repo.asset_payload(asset, library_track)}
                await repo.mark_asset_missing(asset)
                asset = None
            existing = await repo.get_task_by_idempotency(key)
            if existing is None:
                existing = await repo.get_or_create_task(
                    library_track.id,
                    key,
                    max_attempts=max(1, self._settings.download_max_retries),
                    requested_quality=requested_quality,
                )
            elif existing.status == "completed" and asset is None:
                await repo.reset_task(existing)
            await session.commit()
            return {
                "state": "queued" if existing.status == "resolving" else existing.status,
                "task": repo.task_payload(existing, library_track),
            }

    async def retry(self, task_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            repo = LibraryRepository(session)
            task = await session.get(repo_task_type(), task_id)
            if task is None:
                return None
            if task.status == "completed":
                track = await repo.get_track(task.library_track_id)
                return repo.task_payload(task, track)
            task.status = "queued"
            task.attempt_count = 0
            task.bytes_done = 0
            task.bytes_total = None
            task.next_retry_at = None
            task.last_error = None
            task.completed_at = None
            task.heartbeat_at = None
            task.lease_token = None
            task.candidate_snapshot = None
            task.selected_source_id = None
            task.selected_source_track_id = None
            task.selected_quality = None
            task.source_page_url = None
            await session.commit()
            return repo.task_payload(task, None)

    async def assets(self) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            return await LibraryRepository(session).list_assets()

    async def tasks(self) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            return await LibraryRepository(session).list_tasks()

    async def task(self, task_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            repo = LibraryRepository(session)
            task = await session.get(repo_task_type(), task_id)
            if task is None:
                return None
            track = await repo.get_track(task.library_track_id)
            return repo.task_payload(task, track)

    async def summary(self) -> dict[str, Any]:
        async with self._session_factory() as session:
            return await LibraryRepository(session).summary()

    async def asset(self, asset_id: str) -> tuple[Any, Path, Any] | None:
        async with self._session_factory() as session:
            repo = LibraryRepository(session)
            asset = await repo.get_asset(asset_id)
            if asset is None:
                return None
            track = await repo.get_track(asset.library_track_id)
            path = self._asset_path(asset.relative_path)
            if not path.is_file() and asset.status == "ready":
                await repo.mark_asset_missing(asset)
                await session.commit()
            return asset, path, track

    async def delete_asset(self, asset_id: str) -> bool:
        async with self._session_factory() as session:
            repo = LibraryRepository(session)
            asset = await repo.get_asset(asset_id)
            if asset is None:
                return False
            path = self._asset_path(asset.relative_path)
            path.unlink(missing_ok=True)
            await session.delete(asset)
            await session.commit()
            return True

    def _asset_path(self, relative_path: str) -> Path:
        root = self._settings.music_library_dir.resolve()
        path = (root / relative_path).resolve()
        if path != root and root not in path.parents:
            raise ValueError("invalid library asset path")
        return path


def repo_task_type() -> type:
    from app.adapters.persistence.models import DownloadTaskRow

    return DownloadTaskRow

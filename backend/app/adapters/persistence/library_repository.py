from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import (
    DownloadAttemptRow,
    DownloadTaskRow,
    LibraryAssetRow,
    LibrarySourceRefRow,
    LibraryTrackRow,
)
from app.domain.matching import artist_key, is_auto_match, normalize_text, track_key
from app.domain.models import AudioQuality, DownloadCandidate, TrackRef


def _now() -> datetime:
    return datetime.now(UTC)


class LibraryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def find_or_create_track(self, track: TrackRef) -> LibraryTrackRow:
        row = await self.find_track(track)
        if row is not None:
            row.title = track.title
            row.artist = track.artist
            row.album = track.album or row.album
            row.duration_ms = track.duration_ms or row.duration_ms
            row.isrc = track.isrc or row.isrc
            row.version = track.version or row.version
            row.updated_at = _now()
            return row
        row = LibraryTrackRow(
            id=str(uuid.uuid4()),
            title=track.title,
            artist=track.artist,
            album=track.album,
            normalized_title=normalize_text(track.title),
            normalized_artist=artist_key(track.artist),
            duration_ms=track.duration_ms,
            isrc=track.isrc,
            version=track.version,
            created_at=_now(),
            updated_at=_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def find_track(self, track: TrackRef) -> LibraryTrackRow | None:
        clauses = [
            and_(
                LibraryTrackRow.normalized_title == normalize_text(track.title),
                LibraryTrackRow.normalized_artist == artist_key(track.artist),
            )
        ]
        if track.isrc:
            clauses.insert(0, LibraryTrackRow.isrc == track.isrc)
        result = await self._session.execute(select(LibraryTrackRow).where(or_(*clauses)))
        for row in result.scalars().all():
            candidate = TrackRef(
                platform="library",
                external_id=row.id,
                title=row.title,
                artist=row.artist,
                album=row.album,
                duration_ms=row.duration_ms,
                isrc=row.isrc,
                version=row.version,
            )
            if is_auto_match(track, candidate):
                return row
        return None

    async def get_ready_asset(self, track_id: str) -> LibraryAssetRow | None:
        result = await self._session.execute(
            select(LibraryAssetRow)
            .where(
                LibraryAssetRow.library_track_id == track_id,
                LibraryAssetRow.status == "ready",
            )
            .order_by(LibraryAssetRow.downloaded_at.desc().nullslast())
        )
        return result.scalars().first()

    async def get_asset(self, asset_id: str) -> LibraryAssetRow | None:
        return await self._session.get(LibraryAssetRow, asset_id)

    async def get_track(self, track_id: str) -> LibraryTrackRow | None:
        return await self._session.get(LibraryTrackRow, track_id)

    async def add_source_ref(self, track_id: str, candidate: DownloadCandidate) -> None:
        result = await self._session.execute(
            select(LibrarySourceRefRow).where(
                LibrarySourceRefRow.source_id == candidate.source_id,
                LibrarySourceRefRow.source_track_id == candidate.source_track_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            self._session.add(
                LibrarySourceRefRow(
                    id=str(uuid.uuid4()),
                    library_track_id=track_id,
                    source_id=candidate.source_id,
                    source_track_id=candidate.source_track_id,
                    source_page_url=candidate.source_page_url,
                )
            )
        elif candidate.source_page_url:
            row.source_page_url = candidate.source_page_url

    async def get_task_by_idempotency(self, key: str) -> DownloadTaskRow | None:
        result = await self._session.execute(
            select(DownloadTaskRow).where(DownloadTaskRow.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def create_task(
        self,
        track_id: str,
        key: str,
        *,
        max_attempts: int,
        requested_quality: AudioQuality | None = None,
    ) -> DownloadTaskRow:
        row = DownloadTaskRow(
            id=str(uuid.uuid4()),
            idempotency_key=key,
            library_track_id=track_id,
            status="resolving",
            requested_quality=requested_quality.model_dump() if requested_quality else None,
            max_attempts=max_attempts,
            created_at=_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def claim_next_task(self, lease_sec: int) -> DownloadTaskRow | None:
        now = _now()
        stale = datetime.fromtimestamp(now.timestamp() - lease_sec, UTC)
        result = await self._session.execute(
            select(DownloadTaskRow)
            .where(
                or_(
                    DownloadTaskRow.status.in_(["resolving", "queued", "retrying"]),
                    and_(
                        DownloadTaskRow.status == "downloading",
                        or_(DownloadTaskRow.heartbeat_at.is_(None), DownloadTaskRow.heartbeat_at < stale),
                    ),
                ),
                or_(DownloadTaskRow.next_retry_at.is_(None), DownloadTaskRow.next_retry_at <= now),
            )
            .order_by(DownloadTaskRow.created_at.asc())
            .with_for_update(skip_locked=True)
        )
        row = result.scalars().first()
        if row is None:
            return None
        row.status = "downloading"
        row.started_at = row.started_at or now
        row.heartbeat_at = now
        await self._session.flush()
        return row

    async def heartbeat(self, task: DownloadTaskRow, bytes_done: int, bytes_total: int | None) -> None:
        task.bytes_done = bytes_done
        task.bytes_total = bytes_total
        task.heartbeat_at = _now()

    async def mark_failed(self, task: DownloadTaskRow, error: str) -> None:
        task.status = "failed"
        task.last_error = error[:1000]
        task.heartbeat_at = None
        task.completed_at = _now()

    async def save_candidate_snapshot(
        self,
        task: DownloadTaskRow,
        candidates: list[DownloadCandidate],
        selected: DownloadCandidate,
    ) -> None:
        task.status = "queued"
        task.selected_source_id = selected.source_id
        task.selected_source_track_id = selected.source_track_id
        task.source_page_url = selected.source_page_url
        task.selected_quality = selected.quality.model_dump()
        task.candidate_snapshot = [candidate.model_dump() for candidate in candidates]
        task.next_retry_at = None

    async def add_attempt(self, task_id: str, attempt_no: int, source_id: str) -> DownloadAttemptRow:
        row = DownloadAttemptRow(
            id=str(uuid.uuid4()),
            task_id=task_id,
            attempt_no=attempt_no,
            source_id=source_id,
            started_at=_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def complete_task(
        self,
        task: DownloadTaskRow,
        candidate: DownloadCandidate,
        relative_path: str,
        file_size: int,
        sha256: str,
    ) -> LibraryAssetRow:
        quality = candidate.quality
        asset = LibraryAssetRow(
            id=str(uuid.uuid4()),
            library_track_id=task.library_track_id,
            format=quality.format,
            sample_rate_hz=quality.sample_rate_hz,
            bit_depth=quality.bit_depth,
            channels=quality.channels,
            dsd_rate=quality.dsd_rate,
            relative_path=relative_path,
            file_size=file_size,
            sha256=sha256,
            status="ready",
            downloaded_at=_now(),
        )
        self._session.add(asset)
        task.status = "completed"
        task.bytes_done = file_size
        task.bytes_total = file_size
        task.completed_at = _now()
        task.heartbeat_at = None
        await self.add_source_ref(task.library_track_id, candidate)
        await self._session.flush()
        return asset

    async def list_assets(self) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(LibraryAssetRow, LibraryTrackRow)
            .join(LibraryTrackRow, LibraryTrackRow.id == LibraryAssetRow.library_track_id)
            .order_by(LibraryAssetRow.downloaded_at.desc().nullslast())
        )
        return [self._asset_payload(asset, track) for asset, track in result.all()]

    async def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(DownloadTaskRow, LibraryTrackRow)
            .join(LibraryTrackRow, LibraryTrackRow.id == DownloadTaskRow.library_track_id)
            .order_by(DownloadTaskRow.created_at.desc())
            .limit(limit)
        )
        return [self._task_payload(task, track) for task, track in result.all()]

    async def summary(self) -> dict[str, Any]:
        result = await self._session.execute(
            select(DownloadTaskRow.status, func.count()).group_by(DownloadTaskRow.status)
        )
        counts = {str(status): int(count) for status, count in result.all()}
        current = await self._session.execute(
            select(DownloadTaskRow, LibraryTrackRow)
            .join(LibraryTrackRow, LibraryTrackRow.id == DownloadTaskRow.library_track_id)
            .where(DownloadTaskRow.status.in_(["resolving", "queued", "downloading", "retrying"]))
            .order_by(DownloadTaskRow.created_at.asc())
        )
        task_pair = current.first()
        task, track = task_pair if task_pair else (None, None)
        return {
            "counts": counts,
            "active": self._task_payload(task, track) if task else None,
        }

    async def mark_asset_missing(self, asset: LibraryAssetRow) -> None:
        asset.status = "missing"

    @staticmethod
    def _asset_payload(asset: LibraryAssetRow, track: LibraryTrackRow) -> dict[str, Any]:
        return {
            "id": asset.id,
            "track_id": track.id,
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "format": asset.format,
            "sample_rate_hz": asset.sample_rate_hz,
            "bit_depth": asset.bit_depth,
            "channels": asset.channels,
            "dsd_rate": asset.dsd_rate,
            "relative_path": asset.relative_path,
            "file_size": asset.file_size,
            "sha256": asset.sha256,
            "status": asset.status,
            "downloaded_at": asset.downloaded_at.isoformat() if asset.downloaded_at else None,
        }

    @staticmethod
    def _task_payload(
        task: DownloadTaskRow | None, track: LibraryTrackRow | None
    ) -> dict[str, Any] | None:
        if task is None:
            return None
        return {
            "id": task.id,
            "track_id": task.library_track_id,
            "title": track.title if track else None,
            "artist": track.artist if track else None,
            "status": task.status,
            "bytes_done": task.bytes_done,
            "bytes_total": task.bytes_total,
            "progress": (
                task.bytes_done / task.bytes_total
                if task.bytes_total and task.bytes_total > 0
                else None
            ),
            "attempt_count": task.attempt_count,
            "max_attempts": task.max_attempts,
            "selected_source_id": task.selected_source_id,
            "selected_quality": task.selected_quality,
            "source_page_url": task.source_page_url,
            "last_error": task.last_error,
            "created_at": task.created_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }


def task_idempotency_key(track: TrackRef) -> str:
    return track_key(track)

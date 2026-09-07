from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
from mutagen import File as MutagenFile
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence.library_repository import LibraryRepository
from app.adapters.persistence.models import DownloadTaskRow, LibraryTrackRow
from app.download_sources.registry import DownloadSourceRegistry
from app.domain.matching import is_auto_match
from app.domain.models import AudioQuality, DownloadCandidate, TrackRef
from app.settings import Settings

log = structlog.get_logger(__name__)


class DownloadWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: httpx.AsyncClient,
        sources: DownloadSourceRegistry,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._sources = sources
        self._settings = settings
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="musico-download-worker")

    async def shutdown(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                worked = await self.run_once()
                if not worked:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._settings.download_poll_sec)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("download_worker_iteration_failed")
                await asyncio.sleep(self._settings.download_poll_sec)

    async def run_once(self) -> bool:
        async with self._session_factory() as session:
            repo = LibraryRepository(session)
            task = await repo.claim_next_task(self._settings.download_lease_sec)
            if task is None:
                return False
            await session.commit()
        await self._process(task.id)
        return True

    async def _process(self, task_id: str) -> None:
        async with self._session_factory() as session:
            repo = LibraryRepository(session)
            task = await session.get(DownloadTaskRow, task_id)
            if task is None:
                return
            track_row = await repo.get_track(task.library_track_id)
            if track_row is None:
                await repo.mark_failed(task, "library track missing")
                await session.commit()
                return
            track = _track_from_row(track_row)
            candidates = await self._candidate_pool(session, repo, task, track)
            if not candidates:
                await repo.mark_failed(task, "no matching download source")
                await session.commit()
                return
            candidate_index = min(task.attempt_count // max(task.max_attempts, 1), len(candidates) - 1)
            candidate = candidates[candidate_index]
            task.selected_source_id = candidate.source_id
            task.selected_source_track_id = candidate.source_track_id
            task.source_page_url = candidate.source_page_url
            task.selected_quality = candidate.quality.model_dump()
            task.attempt_count += 1
            attempt = await repo.add_attempt(task.id, task.attempt_count, candidate.source_id)
            await session.commit()
            try:
                relative_path, file_size, digest = await self._download(task, candidate, repo)
            except Exception as exc:
                attempt.error = str(exc)[:1000]
                attempt.finished_at = _now()
                if task.attempt_count < len(candidates) * max(task.max_attempts, 1):
                    task.status = "retrying"
                    task.next_retry_at = _now() + timedelta(seconds=min(60, 2 ** task.attempt_count))
                    task.heartbeat_at = None
                    task.last_error = str(exc)[:1000]
                else:
                    await repo.mark_failed(task, str(exc))
                await session.commit()
                log.warning("download_attempt_failed", task_id=task.id, error=str(exc)[:200])
                return
            attempt.finished_at = _now()
            await repo.complete_task(task, candidate, relative_path, file_size, digest)
            await session.commit()

    async def _candidate_pool(
        self,
        session: AsyncSession,
        repo: LibraryRepository,
        task: DownloadTaskRow,
        track: TrackRef,
    ) -> list[DownloadCandidate]:
        if task.candidate_snapshot:
            return [DownloadCandidate.model_validate(item) for item in task.candidate_snapshot]
        results = await asyncio.gather(
            *(record.source.search(track) for record in self._sources.enabled()),
            return_exceptions=True,
        )
        candidates: list[DownloadCandidate] = []
        for result in results:
            if isinstance(result, Exception):
                continue
            candidates.extend(
                candidate
                for candidate in result
                if candidate.source_id in self._sources.sources
                and is_auto_match(
                    track,
                    TrackRef(
                        platform=candidate.source_id,
                        external_id=candidate.source_track_id,
                        title=candidate.title,
                        artist=candidate.artist,
                        album=candidate.album,
                        duration_ms=candidate.duration_ms,
                        isrc=candidate.isrc,
                        version=candidate.version,
                    ),
                )
            )
        if not candidates:
            return []
        candidates.sort(
            key=lambda item: (
                item.quality.sort_key(),
                self._sources.get(item.source_id).priority if self._sources.get(item.source_id) else 0,
            ),
            reverse=True,
        )
        top_quality = candidates[0].quality.sort_key()
        candidates = [item for item in candidates if item.quality.sort_key() == top_quality]
        await repo.save_candidate_snapshot(task, candidates, candidates[0])
        await session.commit()
        return candidates

    async def _download(
        self,
        task: DownloadTaskRow,
        candidate: DownloadCandidate,
        repo: LibraryRepository,
    ) -> tuple[str, int, str]:
        source = self._sources.get(candidate.source_id)
        if source is None:
            raise ValueError("download source missing")
        directory = self._settings.music_library_dir / task.library_track_id
        directory.mkdir(parents=True, exist_ok=True)
        extension = candidate.quality.format.lower().lstrip(".") or "bin"
        part_path = directory / f"{task.id}.part"
        final_path = directory / f"{task.id}.{extension}"
        offset = part_path.stat().st_size if part_path.exists() else 0
        resolved = await source.source.resolve(candidate, offset=offset)
        hostname = (urlparse(resolved.url).hostname or "").lower().rstrip(".")
        if source.hosts and not any(hostname == host or hostname.endswith(f".{host}") for host in source.hosts):
            raise ValueError("download URL host is not allowed")
        headers = dict(resolved.headers)
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        started = time.monotonic()
        async with self._client.stream("GET", resolved.url, headers=headers) as response:
            if response.status_code >= 400:
                raise ValueError(f"download HTTP {response.status_code}")
            content_type = response.headers.get("content-type", "").lower()
            if content_type.startswith("text/html"):
                raise ValueError("download returned HTML instead of audio")
            if offset > 0 and response.status_code != 206:
                offset = 0
                part_path.unlink(missing_ok=True)
                return await self._download(task, candidate, repo)
            if offset > 0:
                content_range = response.headers.get("content-range", "")
                match = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", content_range, re.I)
                if match is None or int(match.group(1)) != offset:
                    raise ValueError("download range response does not resume at requested offset")
            content_length = response.headers.get("content-length")
            total = offset + int(content_length) if content_length and response.status_code == 206 else int(content_length or 0)
            if total > self._settings.download_max_file_size:
                raise ValueError("download exceeds configured size limit")
            mode = "ab" if offset else "wb"
            digest = hashlib.sha256()
            if offset:
                with part_path.open("rb") as existing:
                    while chunk := existing.read(1024 * 1024):
                        digest.update(chunk)
            bytes_done = offset
            with part_path.open(mode) as output:
                async for chunk in response.aiter_bytes(1024 * 1024):
                    if time.monotonic() - started > self._settings.download_timeout_sec:
                        raise TimeoutError("download timeout")
                    bytes_done += len(chunk)
                    if bytes_done > self._settings.download_max_file_size:
                        raise ValueError("download exceeds configured size limit")
                    output.write(chunk)
                    digest.update(chunk)
                    if bytes_done - (task.bytes_done or 0) >= 1024 * 1024:
                        await repo.heartbeat(task, bytes_done, total or None)
                        await repo.commit()
        verified_quality = _verify_audio(part_path, candidate.quality.format)
        candidate.quality = verified_quality
        os.replace(part_path, final_path)
        return str(final_path.relative_to(self._settings.music_library_dir)), bytes_done, digest.hexdigest()


def _track_from_row(row: LibraryTrackRow) -> TrackRef:
    return TrackRef(
        platform="library",
        external_id=row.id,
        title=row.title,
        artist=row.artist,
        album=row.album,
        duration_ms=row.duration_ms,
        isrc=row.isrc,
        version=row.version,
    )


def _now():
    return datetime.now(UTC)


def _verify_audio(path: Path, format_name: str) -> AudioQuality:
    audio = MutagenFile(path)
    if audio is None or getattr(audio, "info", None) is None:
        raise ValueError("downloaded file is not a readable audio file")
    info = audio.info
    sample_rate = getattr(info, "sample_rate", None)
    bit_depth = getattr(info, "bits_per_sample", None)
    channels = getattr(info, "channels", None)
    return AudioQuality(
        format=format_name.lower().lstrip("."),
        sample_rate_hz=int(sample_rate) if sample_rate else None,
        bit_depth=int(bit_depth) if bit_depth else None,
        channels=int(channels) if channels else None,
    )

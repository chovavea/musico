from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urljoin

import httpx
import structlog
from mutagen import File as MutagenFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.http.safety import MAX_HOPS, REDIRECT_STATUSES, assert_outbound_url_allowed
from app.adapters.http.safety import (
    headers_for_redirect as _headers_for_cross_origin_redirect,
)
from app.adapters.persistence.library_repository import LeaseLostError, LibraryRepository
from app.adapters.persistence.models import (
    DownloadAttemptRow,
    DownloadTaskRow,
    LibraryAssetRow,
    LibraryTrackRow,
)
from app.domain.matching import is_auto_match
from app.domain.models import AudioQuality, DownloadCandidate, TrackRef
from app.download_sources.registry import DownloadSourceRegistry
from app.settings import Settings

UrlGuard = Callable[[str, Sequence[str]], Awaitable[None]]

log = structlog.get_logger(__name__)

class DownloadWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: httpx.AsyncClient,
        sources: DownloadSourceRegistry,
        settings: Settings,
        *,
        url_guard: UrlGuard | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._sources = sources
        self._settings = settings
        self._url_guard = url_guard or assert_outbound_url_allowed
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
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self._settings.download_poll_sec
                    )
            except TimeoutError:
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
            task_id = task.id
            lease_token = task.lease_token
            await session.commit()
        await self._process(task_id, lease_token)
        return True

    async def _process(self, task_id: str, lease_token: str | None = None) -> None:
        async with self._session_factory() as session:
            repo = LibraryRepository(session)
            task = await session.get(DownloadTaskRow, task_id)
            if task is None:
                return
            if lease_token is not None and task.lease_token != lease_token:
                return
            track_row = await repo.get_track(task.library_track_id)
            if track_row is None:
                if await repo.mark_failed(task, "library track missing"):
                    self._cleanup_partial(task)
                await session.commit()
                return
            track = _track_from_row(track_row)
            previous_source_id = task.selected_source_id
            previous_source_track_id = task.selected_source_track_id
            candidates = await self._candidate_pool(session, repo, task, track)
            if not await repo.has_lease(task):
                await session.rollback()
                return
            if not candidates:
                error = (
                    "no download source matches requested quality"
                    if task.requested_quality
                    else "no matching download source"
                )
                if await repo.mark_failed(task, error):
                    self._cleanup_partial(task)
                await session.commit()
                return
            candidate_index = min(
                task.attempt_count // max(task.max_attempts, 1), len(candidates) - 1
            )
            candidate = candidates[candidate_index]
            source_changed = (
                previous_source_id != candidate.source_id
                or previous_source_track_id != candidate.source_track_id
            )
            if source_changed:
                self._cleanup_partial(task)
                task.bytes_done = 0
                task.bytes_total = None
            task.selected_source_id = candidate.source_id
            task.selected_source_track_id = candidate.source_track_id
            task.source_page_url = candidate.source_page_url
            task.selected_quality = candidate.quality.model_dump()
            task.attempt_count += 1
            attempt = await repo.add_attempt(task.id, task.attempt_count, candidate.source_id)
            await session.commit()
            try:
                relative_path, file_size, digest = await self._download(task, candidate, repo)
            except LeaseLostError:
                await session.execute(
                    update(DownloadAttemptRow)
                    .where(
                        DownloadAttemptRow.task_id == task.id,
                        DownloadAttemptRow.attempt_no == attempt.attempt_no,
                    )
                    .values(error="download lease lost", finished_at=_now())
                )
                await session.commit()
                log.warning("download_attempt_lease_lost", task_id=task.id)
                return
            except Exception as exc:
                attempt.error = str(exc)[:1000]
                attempt.finished_at = _now()
                if task.attempt_count < len(candidates) * max(task.max_attempts, 1):
                    owned = await repo.schedule_retry(
                        task,
                        str(exc),
                        _now() + timedelta(seconds=min(60, 2**task.attempt_count)),
                    )
                    if not owned:
                        await session.rollback()
                        return
                else:
                    owned = await repo.mark_failed(task, str(exc))
                    if owned:
                        self._cleanup_partial(task)
                    else:
                        await session.rollback()
                        return
                await session.commit()
                log.warning("download_attempt_failed", task_id=task.id, error=str(exc)[:200])
                return
            attempt.finished_at = _now()
            try:
                async with session.begin_nested():
                    await repo.complete_task(task, candidate, relative_path, file_size, digest)
                await session.commit()
            except LeaseLostError:
                await session.execute(
                    update(DownloadAttemptRow)
                    .where(
                        DownloadAttemptRow.task_id == task.id,
                        DownloadAttemptRow.attempt_no == attempt.attempt_no,
                    )
                    .values(error="download lease lost", finished_at=_now())
                )
                await session.commit()
                log.warning("download_completion_lease_lost", task_id=task.id)
                return
            except Exception as exc:
                task_id = task.id
                attempt_no = task.attempt_count
                lease_token = task.lease_token
                await session.rollback()
                await self._record_completion_failure(
                    task_id=task_id,
                    attempt_no=attempt_no,
                    candidate_count=len(candidates),
                    error=str(exc),
                    lease_token=lease_token,
                    relative_path=relative_path,
                )
                log.warning("download_completion_failed", task_id=task_id, error=str(exc)[:200])

    async def _candidate_pool(
        self,
        session: AsyncSession,
        repo: LibraryRepository,
        task: DownloadTaskRow,
        track: TrackRef,
    ) -> list[DownloadCandidate]:
        requested_quality = (
            AudioQuality.model_validate(task.requested_quality)
            if task.requested_quality
            else None
        )
        if task.candidate_snapshot:
            snapshot_candidates = [
                DownloadCandidate.model_validate(item) for item in task.candidate_snapshot
            ]
            if requested_quality is not None:
                snapshot_candidates = [
                    candidate
                    for candidate in snapshot_candidates
                    if candidate.quality.may_match_requested(requested_quality)
                ]
            return snapshot_candidates
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
                and (
                    requested_quality is None
                    or candidate.quality.may_match_requested(requested_quality)
                )
            )
        if not candidates:
            return []
        candidates.sort(
            key=lambda item: (
                item.quality.sort_key(),
                self._sources.get(item.source_id).priority
                if self._sources.get(item.source_id)
                else 0,
            ),
            reverse=True,
        )
        top_quality = candidates[0].quality.sort_key()
        candidates = [item for item in candidates if item.quality.sort_key() == top_quality]
        if not await repo.save_candidate_snapshot(task, candidates, candidates[0]):
            return candidates
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
        directory = self._settings.music_library_dir
        directory.mkdir(parents=True, exist_ok=True)
        extension = candidate.quality.format.lower().lstrip(".") or "bin"
        part_path = directory / f"{task.id}.part"
        final_path = directory / f"{task.id}.{extension}"
        offset = part_path.stat().st_size if part_path.exists() else 0
        resolved = await source.source.resolve(candidate, offset=offset)
        url = str(resolved.url)
        headers = dict(resolved.headers)
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        started = time.monotonic()
        last_heartbeat = started
        bytes_done = offset
        for _hop in range(MAX_HOPS):
            # Validate every hop (allowlist + non-private IPs). Redirects are
            # followed manually so a 302 to an internal host is rejected.
            await self._url_guard(url, source.hosts)
            async with self._client.stream(
                "GET", url, headers=headers, follow_redirects=False
            ) as response:
                status = response.status_code
                if status in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("download redirect missing location")
                    if offset > 0 and status in (301, 302, 303):
                        offset = 0
                        bytes_done = 0
                        headers.pop("Range", None)
                        part_path.unlink(missing_ok=True)
                    next_url = urljoin(str(response.url), location)
                    headers = _headers_for_cross_origin_redirect(headers, url, next_url)
                    url = next_url
                    continue
                if status >= 400:
                    raise ValueError(f"download HTTP {status}")
                content_type = response.headers.get("content-type", "").lower()
                if content_type.startswith("text/html"):
                    raise ValueError("download returned HTML instead of audio")
                if offset > 0 and status != 206:
                    offset = 0
                    bytes_done = 0
                    headers.pop("Range", None)
                    part_path.unlink(missing_ok=True)
                    continue
                if offset > 0:
                    content_range = response.headers.get("content-range", "")
                    match = re.match(
                        r"bytes\s+(\d+)-(\d+)/(\d+|\*)", content_range, re.I
                    )
                    if match is None or int(match.group(1)) != offset:
                        raise ValueError(
                            "download range response does not resume at requested offset"
                        )
                content_length = response.headers.get("content-length")
                total = (
                    offset + int(content_length)
                    if content_length and status == 206
                    else int(content_length or 0)
                )
                if total > self._settings.download_max_file_size:
                    raise ValueError("download exceeds configured size limit")
                digest = hashlib.sha256()
                mode = "ab" if offset else "wb"
                with part_path.open(mode) as output:
                    if offset:
                        await asyncio.to_thread(_hash_file_start, part_path, digest)
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        if time.monotonic() - started > self._settings.download_timeout_sec:
                            raise TimeoutError("download timeout")
                        bytes_done += len(chunk)
                        if bytes_done > self._settings.download_max_file_size:
                            raise ValueError("download exceeds configured size limit")
                        await asyncio.to_thread(_write_and_hash, output, chunk, digest)
                        if bytes_done - (task.bytes_done or 0) >= 1024 * 1024 or (
                            time.monotonic() - last_heartbeat
                            >= max(1.0, self._settings.download_lease_sec / 3)
                        ):
                            if not await repo.heartbeat(task, bytes_done, total or None):
                                raise LeaseLostError
                            await repo.commit()
                            last_heartbeat = time.monotonic()
                break
        else:
            raise ValueError("download exceeded redirect limit")
        try:
            verified_quality = await asyncio.to_thread(
                _verify_audio, part_path, candidate.quality.format
            )
            advertised_dimensions = (
                candidate.quality.sample_rate_hz is not None
                or candidate.quality.bit_depth is not None
                or candidate.quality.channels is not None
                or candidate.quality.dsd_rate is not None
            )
            if advertised_dimensions and not verified_quality.matches_requested(
                candidate.quality
            ):
                raise ValueError("downloaded audio does not match advertised quality")
            if task.requested_quality is not None:
                requested_quality = AudioQuality.model_validate(task.requested_quality)
                if not verified_quality.matches_requested(requested_quality):
                    raise ValueError("downloaded audio does not match requested quality")
        except Exception:
            part_path.unlink(missing_ok=True)
            raise
        candidate.quality = verified_quality
        await asyncio.to_thread(os.replace, part_path, final_path)
        return (
            str(final_path.relative_to(self._settings.music_library_dir)),
            bytes_done,
            digest.hexdigest(),
        )

    def _cleanup_partial(self, task: DownloadTaskRow) -> None:
        self._part_path(task.id).unlink(missing_ok=True)

    def _cleanup_download_files(
        self,
        task_id: str,
        relative_path: str,
        *,
        remove_final: bool = True,
    ) -> None:
        self._part_path(task_id).unlink(missing_ok=True)
        if not remove_final:
            return
        path = (self._settings.music_library_dir / relative_path).resolve()
        root = self._settings.music_library_dir.resolve()
        if path != root and root in path.parents:
            path.unlink(missing_ok=True)

    def _part_path(self, task_id: str) -> Path:
        return self._settings.music_library_dir / f"{task_id}.part"

    async def _record_completion_failure(
        self,
        *,
        task_id: str,
        attempt_no: int,
        candidate_count: int,
        error: str,
        lease_token: str | None,
        relative_path: str,
    ) -> None:
        async with self._session_factory() as session:
            repo = LibraryRepository(session)
            task = await session.get(DownloadTaskRow, task_id)
            if task is None:
                return
            if task.status != "downloading" or task.lease_token != lease_token:
                return
            asset_ref = await session.execute(
                select(LibraryAssetRow.id)
                .where(LibraryAssetRow.relative_path == relative_path)
                .limit(1)
            )
            self._cleanup_download_files(
                task_id,
                relative_path,
                remove_final=asset_ref.first() is None,
            )
            result = await session.execute(
                select(DownloadAttemptRow).where(
                    DownloadAttemptRow.task_id == task_id,
                    DownloadAttemptRow.attempt_no == attempt_no,
                )
            )
            attempt = result.scalar_one_or_none()
            if attempt is not None:
                attempt.error = error[:1000]
                attempt.finished_at = attempt.finished_at or _now()
            if task.attempt_count < candidate_count * max(task.max_attempts, 1):
                task.status = "retrying"
                task.next_retry_at = _now() + timedelta(seconds=min(60, 2**task.attempt_count))
                task.heartbeat_at = None
                task.last_error = error[:1000]
            else:
                await repo.mark_failed(task, error)
            await session.commit()


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


def _write_and_hash(output: BinaryIO, chunk: bytes, digest: Any) -> None:
    """Synchronous disk append + digest update, run via asyncio.to_thread."""
    output.write(chunk)
    digest.update(chunk)


def _hash_file_start(path: Path, digest: Any) -> None:
    """Re-hash an existing .part file before resuming, off the event loop."""
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)


def _verify_audio(path: Path, format_name: str) -> AudioQuality:
    audio = MutagenFile(path)
    if audio is None or getattr(audio, "info", None) is None:
        raise ValueError("downloaded file is not a readable audio file")
    actual_format = _audio_format(audio)
    expected_format = format_name.lower().lstrip(".")
    if actual_format != expected_format:
        raise ValueError("downloaded file format does not match advertised format")
    info = audio.info
    sample_rate = getattr(info, "sample_rate", None)
    bit_depth = getattr(info, "bits_per_sample", None)
    channels = getattr(info, "channels", None)
    return AudioQuality(
        format=actual_format,
        sample_rate_hz=int(sample_rate) if sample_rate else None,
        bit_depth=int(bit_depth) if bit_depth else None,
        channels=int(channels) if channels else None,
    )


def _audio_format(audio: Any) -> str:
    module = type(audio).__module__.lower()
    module_formats = {
        "mutagen.flac": "flac",
        "mutagen.wave": "wav",
        "mutagen.aiff": "aiff",
        "mutagen.dsf": "dsf",
        "mutagen.mp3": "mp3",
        "mutagen.asf": "wma",
        "mutagen.oggvorbis": "ogg",
        "mutagen.oggopus": "opus",
    }
    if module in module_formats:
        return module_formats[module]
    if module == "mutagen.mp4":
        codec = str(getattr(getattr(audio, "info", None), "codec", "")).lower()
        return "alac" if codec == "alac" else "m4a"
    mime_formats = {
        "audio/flac": "flac",
        "audio/wav": "wav",
        "audio/wave": "wav",
        "audio/x-wav": "wav",
        "audio/aiff": "aiff",
        "audio/x-aiff": "aiff",
        "audio/dsf": "dsf",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/ogg": "ogg",
        "audio/opus": "opus",
    }
    for mime in getattr(audio, "mime", ()) or ():
        normalized = str(mime).lower().split(";", 1)[0]
        if normalized in mime_formats:
            return mime_formats[normalized]
    raise ValueError("downloaded file format is unsupported")

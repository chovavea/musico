from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, Protocol

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence.library_repository import LibraryRepository
from app.adapters.persistence.models import DownloadTaskRow, LibraryTrackRow
from app.domain.matching import track_key
from app.domain.models import TrackRef
from app.fallback.sonoma import FallbackLink, SonomaFallback, UrlGuard
from app.settings import Settings

log = structlog.get_logger(__name__)

SOURCE_ID = "sonoma"
SOURCE_NAME = "Sonoma"
_POSITIVE_OUTCOMES = frozenset({"jumped"})
_CACHE_LIMIT = 512


class Resolver(Protocol):
    async def resolve(self, track: TrackRef) -> FallbackLink: ...


class FallbackService:
    """Link-out fallback: only ever runs after a download task reached ``failed``.

    The site's WAV uploads live behind a Quark share link, so nothing is
    downloaded here; the browser is handed the share URL instead.  Results are
    cached in-process (success long, failure short) and every answer is recorded
    for the health page.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: httpx.AsyncClient,
        settings: Settings,
        *,
        resolver: Resolver | None = None,
        url_guard: UrlGuard | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._resolver = resolver or _build_resolver(client, settings, url_guard)

    @property
    def enabled(self) -> bool:
        return self._resolver is not None

    @property
    def source_name(self) -> str:
        return SOURCE_NAME

    async def resolve_task(self, task_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            repo = LibraryRepository(session)
            task = await session.get(DownloadTaskRow, task_id)
            if task is None:
                return None
            track_row = await repo.get_track(task.library_track_id)
            track = _track_ref(track_row) if track_row is not None else None
            if task.status != "failed":
                return _payload(task_id, "not_failed", track=track)
            if self._resolver is None:
                return _payload(task_id, "disabled", track=track)
            key = track_key(track) if track is not None else f"task:{task_id}"
            cached = self._cached(key)
            if cached is not None:
                return {**cached, "task_id": task_id, "cached": True}
            link = (
                await self._resolver.resolve(track)
                if track is not None
                else FallbackLink(outcome="not_found", error="曲目信息缺失")
            )
            payload = _payload(task_id, link.outcome, track=track, link=link)
            self._remember(key, link, payload)
            await repo.record_fallback_event(
                task_id=task_id,
                track_id=task.library_track_id,
                title=track.title if track is not None else "",
                artist=track.artist if track is not None else "",
                source_id=SOURCE_ID,
                trigger="fallback_request",
                outcome=link.outcome,
                detail=link.detail or link.error,
                share_url=link.share_url,
                page_url=link.page_url,
            )
            await session.commit()
            log.info(
                "download_fallback_resolved",
                task_id=task_id,
                outcome=link.outcome,
                cached=False,
            )
            return payload

    async def health(self, limit: int) -> dict[str, Any]:
        cap = max(1, limit)
        async with self._session_factory() as session:
            repo = LibraryRepository(session)
            # Display mix and scoring window are separate queries: download_failed
            # rows are more frequent and would otherwise crowd fallback_request
            # out of a single ``limit`` slice, zeroing consecutive_failures.
            events = await repo.list_fallback_events(cap)
            attempts = await repo.list_fallback_events(cap, trigger="fallback_request")
            counts = await repo.fallback_event_counts()
        return {
            "enabled": self.enabled,
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "counts": counts,
            "download_failed_total": counts.get("download_failed:failed", 0),
            "last_success_at": _first_timestamp(
                attempts, lambda outcome: outcome in _POSITIVE_OUTCOMES
            ),
            "last_failure_at": _first_timestamp(
                attempts, lambda outcome: outcome not in _POSITIVE_OUTCOMES
            ),
            "consecutive_failures": _consecutive_failures(attempts),
            "events": events,
        }

    def _cached(self, key: str) -> dict[str, Any] | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if expires_at <= time.monotonic():
            self._cache.pop(key, None)
            return None
        return payload

    def _remember(self, key: str, link: FallbackLink, payload: dict[str, Any]) -> None:
        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()
        ttl = (
            self._settings.fallback_positive_ttl_sec
            if link.outcome in _POSITIVE_OUTCOMES
            else self._settings.fallback_negative_ttl_sec
        )
        self._cache[key] = (time.monotonic() + max(0, ttl), payload)


def _build_resolver(
    client: httpx.AsyncClient,
    settings: Settings,
    url_guard: UrlGuard | None,
) -> SonomaFallback | None:
    base_url = str(settings.fallback_base_url or "").strip()
    if not base_url:
        log.info("download_fallback_disabled")
        return None
    extra_hosts: Sequence[str] = tuple(
        item.strip() for item in str(settings.fallback_extra_hosts or "").split(",") if item.strip()
    )
    try:
        return SonomaFallback(
            client,
            base_url,
            extra_hosts=extra_hosts,
            url_guard=url_guard,
        )
    except ValueError as exc:
        log.warning("download_fallback_disabled", error=str(exc))
        return None


def _track_ref(row: LibraryTrackRow) -> TrackRef:
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


def _payload(
    task_id: str,
    outcome: str,
    *,
    track: TrackRef | None = None,
    link: FallbackLink | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "source_id": SOURCE_ID,
        "source_name": SOURCE_NAME,
        "outcome": outcome,
        "url": link.share_url if link is not None else None,
        "page_url": link.page_url if link is not None else None,
        "detail": link.detail if link is not None else None,
        "error": link.error if link is not None else None,
        "title": track.title if track is not None else None,
        "artist": track.artist if track is not None else None,
    }


def _first_timestamp(attempts: list[dict[str, Any]], predicate: Any) -> str | None:
    for event in attempts:
        if predicate(str(event.get("outcome"))):
            return str(event.get("created_at") or "") or None
    return None


def _consecutive_failures(attempts: list[dict[str, Any]]) -> int:
    count = 0
    for event in attempts:
        if str(event.get("outcome")) in _POSITIVE_OUTCOMES:
            break
        count += 1
    return count

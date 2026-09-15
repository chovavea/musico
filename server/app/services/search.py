from __future__ import annotations

import asyncio
import copy
import re
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence.models import DownloadTaskRow, LibraryAssetRow, LibraryTrackRow
from app.domain.matching import (
    folded_artist_names,
    is_same_recording,
    normalize_text,
    title_match_key,
)
from app.domain.models import TrackRef
from app.domain.zh_t2s import fold_traditional
from app.plugins._registry import PluginRecord, PluginRegistry
from app.services.preview_telemetry import RATES

log = structlog.get_logger(__name__)

SearchKind = Literal["suggest", "full"]

MIN_QUERY_LENGTH = 1
MAX_QUERY_LENGTH = 200
SUGGEST_LIMIT = 5
FULL_LIMIT = 100
MAX_LIMIT = 100
_CACHE_MAX_ITEMS = 128
_SUGGEST_TTL_SEC = 20.0
_FULL_TTL_SEC = 45.0
# Ceiling for one fan-out. Platforms answer in ~0.25-0.8 s, so 2 s leaves roughly
# 2.5x headroom while a hung provider cannot hold the whole search (and the
# browser) for the 15 s per-request timeout.
_SEARCH_BUDGET_SEC = 2.0


@dataclass(frozen=True)
class _SearchCandidate:
    track: TrackRef
    search_rank: int


@dataclass
class _SearchGroup:
    candidates: list[_SearchCandidate]
    first_rank: int
    first_platform: str


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    query: str
    kind: SearchKind
    groups: list[_SearchGroup]
    platforms: list[dict[str, Any]]
    partial: bool


def _merge_keys(track: TrackRef) -> tuple[str, ...]:
    """Bucket keys a track can be merged through.

    Every pair ``is_same_recording`` accepts shares at least one of these keys:
    an identical ISRC, or the same (繁简 folded) title plus one artist name the
    two tracks have in common. The title alone would not be enough: a popular
    single comes back as hundreds of same-titled rows from different artists,
    and comparing all of them made the merge quadratic again (~640 ms for 322
    candidates against ~9 ms with the artist in the key).
    """
    keys: list[str] = []
    if track.isrc:
        keys.append(f"isrc:{track.isrc.casefold()}")
    title = title_match_key(track.title)
    if title:
        keys.extend(
            f"title:{title}|artist:{name}" for name in folded_artist_names(track.artist)
        )
    return tuple(keys)


class SearchService:
    """Search all registered platform plugins and merge equivalent tracks in memory."""

    def __init__(
        self,
        registry: PluginRegistry,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._registry = registry
        self._session_factory = session_factory
        self._cache: dict[tuple[str, SearchKind, int], _CacheEntry] = {}

    async def search(
        self,
        query: str,
        *,
        kind: SearchKind = "full",
        limit: int | None = None,
    ) -> dict[str, Any]:
        cleaned = " ".join(query.split())
        effective_limit = self._effective_limit(kind, limit)
        if len(cleaned) > MAX_QUERY_LENGTH:
            return self._empty_payload(cleaned[:MAX_QUERY_LENGTH], kind, reason="query_too_long")
        if len(cleaned) < MIN_QUERY_LENGTH:
            return self._empty_payload(cleaned, kind, reason="query_too_short")

        key = (cleaned.casefold(), kind, effective_limit)
        cached = self._cache.get(key)
        if cached is not None:
            if cached.expires_at > time.monotonic():
                return await self._payload_from_groups(cached)
            self._cache.pop(key, None)

        records = [
            record for record in self._registry.plugins.values() if record.search is not None
        ]
        query_limit = effective_limit
        attempts = [
            (record, asyncio.create_task(self._search_record(record, cleaned, query_limit)))
            for record in records
        ]
        if attempts:
            await self._await_platforms([task for _, task in attempts])

        platform_status: list[dict[str, Any]] = []
        candidates: list[_SearchCandidate] = []
        for record, task in attempts:
            # Membership in wait()'s pending set is not the same as "timed out":
            # cancel() is ignored once a task has a result, so a platform that
            # finished its last await just as the budget ended must still count.
            if not task.done() or task.cancelled():
                log.warning(
                    "search_platform_timeout",
                    platform=record.plugin_id,
                    budget_sec=_SEARCH_BUDGET_SEC,
                )
                platform_status.append(
                    {
                        "id": record.plugin_id,
                        "name": record.name,
                        "status": "error",
                        "reason": "timeout",
                        "result_count": 0,
                    }
                )
                continue
            error = task.exception()
            if error is not None:
                log.warning(
                    "search_platform_failed",
                    platform=record.plugin_id,
                    error_type=type(error).__name__,
                    error=str(error),
                )
                platform_status.append(
                    {
                        "id": record.plugin_id,
                        "name": record.name,
                        "status": "error",
                        "reason": "error",
                        "result_count": 0,
                    }
                )
                continue
            found = task.result()
            candidates.extend(
                _SearchCandidate(track=track, search_rank=index)
                for index, track in enumerate(found)
            )
            platform_status.append(
                {
                    "id": record.plugin_id,
                    "name": record.name,
                    "status": "ok" if found else "empty",
                    "result_count": len(found),
                }
            )

        groups = self._merge_tracks(candidates)[:effective_limit]
        partial = any(item["status"] == "error" for item in platform_status) and any(
            item["status"] in {"ok", "empty"} for item in platform_status
        )
        cached = _CacheEntry(
            expires_at=time.monotonic()
            + (_SUGGEST_TTL_SEC if kind == "suggest" else _FULL_TTL_SEC),
            query=cleaned,
            kind=kind,
            groups=groups,
            platforms=platform_status,
            partial=partial,
        )
        # A platform that ran out of budget is about to recover, so its absence
        # must not be remembered: caching it would hide that platform for the
        # whole TTL and the user's own retry could not bring it back.
        if not any(item.get("reason") == "timeout" for item in platform_status):
            self._store_cache(key, cached)
        return await self._payload_from_groups(cached)

    @staticmethod
    async def _await_platforms(
        tasks: list[asyncio.Task[list[TrackRef]]],
    ) -> None:
        """Wait for the fan-out, up to a budget, then cancel whatever is still open.

        ``asyncio.gather`` would either wait forever or throw away the platforms
        that already answered. Timed-out tasks are cancelled; a task that still
        produces a result is kept by the caller via ``task.cancelled()``.
        """
        _, pending = await asyncio.wait(tasks, timeout=_SEARCH_BUDGET_SEC)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _search_record(
        self,
        record: PluginRecord,
        query: str,
        limit: int,
    ) -> list[TrackRef]:
        if record.search is None:
            return []
        from app.domain.models import TrackQuery

        found = await record.search.search(TrackQuery(title=query, limit=limit))
        usable = [
            track
            for track in found[:limit]
            if track.platform == record.plugin_id
            and track.external_id
            and track.title.strip()
            and track.artist.strip()
        ]
        relevant = [track for track in usable if self._query_relevant(query, track)]
        if relevant:
            return relevant
        # Latin-script queries (for example "Jay Chou" for 周杰伦) cannot be
        # confirmed by substring matching. Keep the provider ranking then.
        # CJK queries that match nothing should stay empty so unrelated hot
        # songs are not shown as if they were hits.
        return usable if self._cross_script_query(query) else []

    @staticmethod
    def _search_text(value: str) -> str:
        return fold_traditional(normalize_text(value))

    @staticmethod
    def _cross_script_query(query: str) -> bool:
        text = unicodedata.normalize("NFKC", query)
        has_latin = bool(re.search(r"[A-Za-z]", text))
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", text))
        return has_latin and not has_cjk

    @staticmethod
    def _query_relevant(query: str, track: TrackRef) -> bool:
        """Reject provider fallbacks while retaining title and artist substrings."""
        normalized_query = SearchService._search_text(query)
        title = SearchService._search_text(track.title)
        artist = SearchService._search_text(track.artist)
        if not normalized_query or not title or not artist:
            return False

        fields = (title, artist, f"{title}{artist}", f"{artist}{title}")
        if any(normalized_query in field for field in fields):
            return True

        raw_terms = re.split(
            r"[\s\-–—·•|/,_，、]+",
            unicodedata.normalize("NFKC", query).casefold(),
        )
        terms = [term for value in raw_terms if (term := SearchService._search_text(value))]
        if len(terms) > 1 and all(
            any(term in field for field in (title, artist)) for term in terms
        ):
            return True

        # Compact title+artist queries sometimes carry harmless words around the
        # metadata. Requiring both fields prevents a short provider fallback from
        # being accepted merely because its title occurs inside a longer query.
        return title in normalized_query and artist in normalized_query

    @staticmethod
    def _effective_limit(kind: SearchKind, limit: int | None) -> int:
        default = SUGGEST_LIMIT if kind == "suggest" else FULL_LIMIT
        if limit is None:
            return default
        return max(1, min(int(limit), MAX_LIMIT))

    def _merge_tracks(self, candidates: list[_SearchCandidate]) -> list[_SearchGroup]:
        """Group equivalent recordings without comparing every pair.

        Candidates are indexed by :func:`_merge_keys`, so a candidate is only
        compared against groups sharing a key. ``is_same_recording`` still makes
        the final call and the earliest matching group wins, which keeps the
        partition — and therefore the ordering — identical to an all-pairs scan
        while the work stays close to linear.
        """
        groups: list[_SearchGroup] = []
        indexed: dict[str, list[tuple[int, _SearchGroup]]] = {}
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            track = candidate.track
            identity = (track.platform, track.external_id)
            if identity in seen:
                continue
            seen.add(identity)
            keys = _merge_keys(track)
            matches = [
                (index, group)
                for key in keys
                for index, group in indexed.get(key, ())
                if any(
                    existing.track.platform != track.platform
                    and is_same_recording(existing.track, track)
                    for existing in group.candidates
                )
            ]
            if matches:
                index, group = min(matches, key=lambda item: item[0])
                group.candidates.append(candidate)
                if candidate.search_rank < group.first_rank or (
                    candidate.search_rank == group.first_rank
                    and track.platform < group.first_platform
                ):
                    group.first_rank = candidate.search_rank
                    group.first_platform = track.platform
            else:
                index = len(groups)
                group = _SearchGroup(
                    candidates=[candidate],
                    first_rank=candidate.search_rank,
                    first_platform=track.platform,
                )
                groups.append(group)
            for key in keys:
                entries = indexed.setdefault(key, [])
                if all(entry is not group for _, entry in entries):
                    entries.append((index, group))
        groups.sort(key=lambda group: (group.first_rank, group.first_platform))
        return groups

    async def _payload_from_groups(self, cached: _CacheEntry) -> dict[str, Any]:
        annotations = await self._library_annotations(
            [candidate.track for group in cached.groups for candidate in group.candidates]
        )
        return {
            "query": cached.query,
            "type": cached.kind,
            "items": [self._group_payload(group, annotations) for group in cached.groups],
            "platforms": copy.deepcopy(cached.platforms),
            "partial": cached.partial,
        }

    def _group_payload(
        self,
        group: _SearchGroup,
        annotations: dict[tuple[str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        candidates = sorted(
            group.candidates,
            key=lambda candidate: self._candidate_sort_key(candidate, annotations),
        )
        selected = candidates[0]
        candidate_payloads = [
            self._track_payload(
                candidate,
                annotation=annotations.get(self._key(candidate.track)),
            )
            for candidate in candidates
        ]
        selected_annotation = annotations.get(self._key(selected.track), {})
        return {
            **self._track_payload(selected, annotation=selected_annotation),
            "platforms": candidate_payloads,
            "platform_count": len(candidate_payloads),
        }

    def _candidate_sort_key(
        self,
        candidate: _SearchCandidate,
        annotations: dict[tuple[str, str], dict[str, Any]],
    ) -> tuple[int, float, int, str]:
        annotation = annotations.get(self._key(candidate.track), {})
        library_score = 0 if annotation.get("library_status") == "ready" else 1
        return (
            library_score,
            -RATES.target_rate(candidate.track.platform),
            candidate.search_rank,
            candidate.track.platform,
        )

    @staticmethod
    def _track_payload(
        candidate: _SearchCandidate,
        *,
        annotation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        track = candidate.track
        annotation = annotation or {}
        return {
            "platform": track.platform,
            "external_id": track.external_id,
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "duration_ms": track.duration_ms,
            "isrc": track.isrc,
            "version": track.version,
            "cover_url": track.cover_url,
            "official_url": track.official_url,
            "search_rank": candidate.search_rank,
            "library_status": annotation.get("library_status"),
            "library_asset_id": annotation.get("library_asset_id"),
            "active_download_id": annotation.get("active_download_id"),
        }

    async def _library_annotations(
        self,
        tracks: list[TrackRef],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        if not tracks:
            return {}
        try:
            async with self._session_factory() as session:
                result = await session.execute(select(LibraryTrackRow))
                rows = result.scalars().all()
                if not rows:
                    return {}
                # Equality on stored (unfolded) keys misses 繁/简 and ISRC-only
                # pairs; is_same_recording already folds, so match in Python.
                matched_rows: list[Any] = []
                seen_ids: set[str] = set()
                for track in tracks:
                    matched = self._matching_library_track(track, rows)
                    if matched is None or matched.id in seen_ids:
                        continue
                    seen_ids.add(matched.id)
                    matched_rows.append(matched)
                if not matched_rows:
                    return {}
                matched_ids = [row.id for row in matched_rows]
                assets_result = await session.execute(
                    select(LibraryAssetRow)
                    .where(
                        LibraryAssetRow.library_track_id.in_(matched_ids),
                        LibraryAssetRow.status == "ready",
                    )
                    .order_by(LibraryAssetRow.downloaded_at.desc().nullslast())
                )
                assets: dict[str, LibraryAssetRow] = {}
                for asset in assets_result.scalars().all():
                    assets.setdefault(asset.library_track_id, asset)
                task_result = await session.execute(
                    select(DownloadTaskRow).where(
                        DownloadTaskRow.library_track_id.in_(matched_ids),
                        DownloadTaskRow.status.in_(
                            ["resolving", "queued", "downloading", "retrying"]
                        ),
                    )
                )
                tasks = {task.library_track_id: task for task in task_result.scalars().all()}
        except SQLAlchemyError:
            return {}

        return self._annotate_tracks(tracks, matched_rows, assets, tasks)

    @classmethod
    def _annotate_tracks(
        cls,
        tracks: Sequence[TrackRef],
        rows: Sequence[Any],
        assets: Mapping[str, Any],
        tasks: Mapping[str, Any],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        annotations: dict[tuple[str, str], dict[str, Any]] = {}
        for track in tracks:
            matched_track = cls._matching_library_track(track, rows)
            if matched_track is None:
                continue
            matched_asset = assets.get(matched_track.id)
            matched_task = tasks.get(matched_track.id)
            annotations[cls._key(track)] = {
                "library_status": getattr(matched_asset, "status", None) if matched_asset else None,
                "library_asset_id": getattr(matched_asset, "id", None) if matched_asset else None,
                "active_download_id": getattr(matched_task, "id", None) if matched_task else None,
            }
        return annotations

    @classmethod
    def _matching_library_track(cls, track: TrackRef, rows: Sequence[Any]) -> Any | None:
        matched = [row for row in rows if is_same_recording(track, cls._library_ref(row))]
        if not matched:
            return None
        return matched[0]

    @staticmethod
    def _library_ref(row: Any) -> TrackRef:
        return TrackRef(
            platform="library",
            external_id=str(row.id),
            title=row.title,
            artist=row.artist,
            album=row.album,
            duration_ms=row.duration_ms,
            isrc=row.isrc,
            version=row.version,
        )

    @staticmethod
    def _key(track: TrackRef) -> tuple[str, str]:
        return track.platform, track.external_id

    def _store_cache(
        self,
        key: tuple[str, SearchKind, int],
        entry: _CacheEntry,
    ) -> None:
        if len(self._cache) >= _CACHE_MAX_ITEMS:
            oldest = min(self._cache, key=lambda item: self._cache[item].expires_at)
            self._cache.pop(oldest, None)
        self._cache[key] = entry

    @staticmethod
    def _empty_payload(
        query: str,
        kind: SearchKind,
        *,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "query": query,
            "type": kind,
            "items": [],
            "platforms": [],
            "partial": False,
            "reason": reason,
        }

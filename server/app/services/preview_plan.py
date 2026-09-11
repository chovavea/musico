from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import structlog

from app.domain.matching import is_cross_platform_match, track_match_score
from app.domain.models import TrackQuery, TrackRef
from app.plugins._registry import PluginRecord, PluginRegistry
from app.services.preview_telemetry import RATES, RateStore

log = structlog.get_logger(__name__)

_QUALITY_RANK = {"medium": 0, "low": 1}
_UNKNOWN_QUALITY_RANK = 2
_CANDIDATE_POOL_FACTOR = 3


@dataclass(frozen=True)
class PreviewPolicy:
    """Runtime knobs for borrowing a preview from another platform."""

    cross_platform: bool = True
    match_min_score: float = 0.94
    max_candidates: int = 2
    # One budget for the whole cross-platform attempt. Individual search / parse
    # calls are deliberately not capped: a slow answer is still a usable answer,
    # and cutting it short would look like "this platform cannot play the song".
    deadline_sec: float = 60.0
    negative_ttl_sec: float = 180.0
    positive_ttl_sec: float = 600.0

    @classmethod
    def from_settings(cls, settings: object) -> PreviewPolicy:
        return cls(
            cross_platform=bool(getattr(settings, "preview_cross_platform", True)),
            match_min_score=float(getattr(settings, "preview_match_min_score", 0.94)),
            max_candidates=int(getattr(settings, "preview_max_candidates", 2)),
            deadline_sec=float(getattr(settings, "preview_deadline_sec", 60.0)),
            negative_ttl_sec=float(getattr(settings, "preview_negative_ttl_sec", 180.0)),
            positive_ttl_sec=float(getattr(settings, "preview_positive_ttl_sec", 600.0)),
        )


@dataclass(frozen=True)
class PreviewTarget:
    platform: str
    external_id: str
    title: str
    artist: str
    url: str
    match_score: float
    rate: float
    search_rank: int
    quality_rank: int


def platform_order_key(
    record: PluginRecord, origin: TrackRef, rates: RateStore
) -> tuple[float, str]:
    """Order platforms by learned playability; the platform id only breaks ties.

    There is deliberately no configured platform priority: a cold pair starts at
    the same 0.5 prior for every platform, and history decides from there.
    """
    return (-rates.rate(origin.platform, record.plugin_id), record.plugin_id)


def ordered_providers(
    track: TrackRef,
    registry: PluginRegistry,
    rates: RateStore = RATES,
) -> list[PluginRecord]:
    providers = [
        record
        for record in registry.plugins.values()
        if record.plugin_id != track.platform
        and record.search is not None
        and record.preview is not None
    ]
    providers.sort(key=lambda record: platform_order_key(record, track, rates))
    return providers


class PreviewPlanner:
    """Walk the other platforms one at a time, lazily.

    At most one outbound request is in flight: a platform is only searched after
    the previous one failed to produce an audio stream, and the caller stops
    pulling as soon as something plays. That keeps the request footprint small
    and never fans out to several providers at once.
    """

    def __init__(
        self,
        track: TrackRef,
        registry: PluginRegistry,
        policy: PreviewPolicy,
        *,
        rates: RateStore = RATES,
    ) -> None:
        self.track = track
        self.policy = policy
        self.rates = rates
        self.providers = ordered_providers(track, registry, rates) if policy.cross_platform else []
        self.contacted: list[str] = []
        self.attempted = False
        self.current_platform: str | None = None

    @property
    def searched(self) -> bool:
        """Whether any platform's search actually answered."""
        return bool(self.contacted)

    @property
    def platforms(self) -> list[str]:
        return [record.plugin_id for record in self.providers]

    async def iter_targets(self) -> AsyncIterator[PreviewTarget]:
        for record in self.providers:
            self.current_platform = record.plugin_id
            async for target in self._platform_targets(record):
                self.attempted = True
                yield target

    async def _platform_targets(self, record: PluginRecord) -> AsyncIterator[PreviewTarget]:
        search, preview = record.search, record.preview
        if search is None or preview is None:  # pragma: no cover - filtered above
            return
        query = TrackQuery(
            title=self.track.title,
            artist=self.track.artist,
            album=self.track.album,
            duration_ms=self.track.duration_ms,
            isrc=self.track.isrc,
            limit=max(self.policy.max_candidates * _CANDIDATE_POOL_FACTOR, 5),
        )
        try:
            found = await search.search(query)
        except Exception as exc:
            log.info(
                "preview_search_unavailable",
                platform=record.plugin_id,
                error_type=type(exc).__name__,
            )
            return
        self.contacted.append(record.plugin_id)
        ranked = self._rank(found, record.plugin_id)
        for score, index, candidate in ranked[: self.policy.max_candidates]:
            try:
                info = await preview.preview(candidate)
            except Exception as exc:
                log.info(
                    "preview_url_unavailable",
                    platform=record.plugin_id,
                    error_type=type(exc).__name__,
                )
                continue
            if not info.preview_url:
                continue
            yield PreviewTarget(
                platform=candidate.platform,
                external_id=candidate.external_id,
                title=candidate.title,
                artist=candidate.artist,
                url=info.preview_url,
                match_score=score,
                rate=self.rates.rate(self.track.platform, candidate.platform),
                search_rank=index,
                quality_rank=_QUALITY_RANK.get(str(info.quality or ""), _UNKNOWN_QUALITY_RANK),
            )

    def _rank(self, found: list[TrackRef], platform: str) -> list[tuple[float, int, TrackRef]]:
        scored: list[tuple[float, int, TrackRef]] = []
        for index, candidate in enumerate(found):
            if candidate.platform != platform:
                continue
            if not is_cross_platform_match(
                self.track, candidate, min_score=self.policy.match_min_score
            ):
                continue
            scored.append((track_match_score(self.track, candidate), index, candidate))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored

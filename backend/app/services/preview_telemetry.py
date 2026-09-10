from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.adapters.persistence.models import PreviewEventRow, PreviewSourceStatRow
from app.domain.matching import track_key
from app.domain.models import TrackRef

log = structlog.get_logger(__name__)

_DEFAULT_RATE = 0.5
_MIN_SAMPLES = 3
_STATS_WINDOW_DAYS = 7
_EVENT_RETENTION_DAYS = 30


@dataclass
class _Counts:
    success: int = 0
    failure: int = 0

    @property
    def total(self) -> int:
        return self.success + self.failure

    def rate(self) -> float:
        return (self.success + 1) / (self.total + 2)


class RateStore:
    """Smoothed playability for each (origin, target) platform pair.

    The estimate is a Beta posterior ``(success + 1) / (total + 2)``, so an
    unseen pair starts at 0.5 and no platform is privileged by configuration.
    Pairs without enough samples fall back to the target platform overall and
    then to the global average.
    """

    def __init__(self, min_samples: int = _MIN_SAMPLES) -> None:
        self._min_samples = min_samples
        self._pairs: dict[tuple[str, str], _Counts] = {}
        self._targets: dict[str, _Counts] = {}
        self._global = _Counts()

    def record(self, origin: str, target: str, ok: bool, *, samples: int = 1) -> None:
        for counts in (
            self._pairs.setdefault((origin, target), _Counts()),
            self._targets.setdefault(target, _Counts()),
            self._global,
        ):
            if ok:
                counts.success += samples
            else:
                counts.failure += samples

    def rate(self, origin: str, target: str) -> float:
        for counts in (
            self._pairs.get((origin, target)),
            self._targets.get(target),
            self._global,
        ):
            if counts is not None and counts.total >= self._min_samples:
                return counts.rate()
        return _DEFAULT_RATE

    def clear(self) -> None:
        self._pairs.clear()
        self._targets.clear()
        self._global = _Counts()


@dataclass
class CachedTarget:
    platform: str
    external_id: str
    url: str
    match_score: float | None


class PreviewCache:
    """Short-lived memory cache keyed by ``platform:external_id`` of the origin song."""

    def __init__(self) -> None:
        self._positive: dict[str, tuple[float, CachedTarget]] = {}
        self._negative: dict[str, float] = {}

    def positive(self, key: str) -> CachedTarget | None:
        entry = self._positive.get(key)
        if entry is None:
            return None
        if entry[0] <= time.monotonic():
            self._positive.pop(key, None)
            return None
        return entry[1]

    def negative(self, key: str) -> bool:
        expires = self._negative.get(key)
        if expires is None:
            return False
        if expires <= time.monotonic():
            self._negative.pop(key, None)
            return False
        return True

    def store_positive(self, key: str, target: CachedTarget, ttl_sec: float) -> None:
        self._positive[key] = (time.monotonic() + ttl_sec, target)
        self._negative.pop(key, None)

    def invalidate_positive(self, key: str) -> None:
        """Drop a positive entry whose signed URL no longer opens.

        Signed preview URLs expire before the entry does, and keeping a dead one
        would make every later click pay for a failed open before searching again.
        """
        self._positive.pop(key, None)

    def store_negative(self, key: str, ttl_sec: float) -> None:
        self._negative[key] = time.monotonic() + ttl_sec

    def clear(self) -> None:
        self._positive.clear()
        self._negative.clear()


RATES = RateStore()
CACHE = PreviewCache()


def reset_preview_telemetry() -> None:
    """Drop cached decisions and rate estimates (used by tests and reloads)."""
    RATES.clear()
    CACHE.clear()


def cache_key(track: TrackRef) -> str:
    return f"{track.platform}:{track.external_id}"


@dataclass
class PreviewEvent:
    track: TrackRef
    tier: str
    status: str
    source_platform: str | None = None
    source_external_id: str | None = None
    match_score: float | None = None
    error: str | None = None
    latency_ms: int | None = None
    cached: bool = False


async def publish(event: PreviewEvent, *, session_factory: object | None = None) -> None:
    """Record where a stream came from: structured log, rate store and audit row.

    A positive-cache hit replays a decision that was already recorded when the URL
    was first resolved. Counting it again would let a single upstream success vote
    once per click, so it is logged but neither sampled nor written as a new row.
    """
    if event.tier == "T2" and event.source_platform and not event.cached:
        RATES.record(event.track.platform, event.source_platform, event.status == "ok")
    log.info(
        "preview_source_selected",
        origin_platform=event.track.platform,
        external_id=event.track.external_id,
        tier=event.tier,
        status=event.status,
        source_platform=event.source_platform,
        match_score=event.match_score,
        latency_ms=event.latency_ms,
        error=event.error,
        cached=event.cached,
    )
    if session_factory is None or event.cached:
        return
    row = PreviewEventRow(
        track_key=track_key(event.track),
        origin_platform=event.track.platform,
        external_id=event.track.external_id,
        title=event.track.title,
        artist=event.track.artist,
        tier=event.tier,
        source_platform=event.source_platform,
        source_external_id=event.source_external_id,
        match_score=event.match_score,
        status=event.status,
        error=event.error,
        latency_ms=event.latency_ms,
    )
    try:
        async with session_factory() as session:  # type: ignore[operator]
            session.add(row)
            await session.commit()
    except Exception as exc:  # diagnostics must never break playback
        log.warning("preview_event_write_failed", error_type=type(exc).__name__)


async def prewarm(session_factory: object) -> None:
    """Seed the rate store from recent events and refresh the aggregate table."""
    since = datetime.now(UTC) - timedelta(days=_STATS_WINDOW_DAYS)
    try:
        async with session_factory() as session:  # type: ignore[operator]
            result = await session.execute(
                select(
                    PreviewEventRow.origin_platform,
                    PreviewEventRow.source_platform,
                    func.count().filter(PreviewEventRow.status == "ok"),
                    func.count().filter(PreviewEventRow.status != "ok"),
                    func.avg(PreviewEventRow.latency_ms),
                )
                .where(
                    PreviewEventRow.created_at >= since,
                    PreviewEventRow.tier == "T2",
                    PreviewEventRow.source_platform.is_not(None),
                )
                .group_by(PreviewEventRow.origin_platform, PreviewEventRow.source_platform)
            )
            now = datetime.now(UTC)
            for origin, target, success, failure, latency in result.all():
                if target is None:
                    continue
                RATES.record(str(origin), str(target), True, samples=int(success or 0))
                RATES.record(str(origin), str(target), False, samples=int(failure or 0))
                await session.execute(
                    pg_insert(PreviewSourceStatRow)
                    .values(
                        origin_platform=str(origin),
                        target_platform=str(target),
                        success=int(success or 0),
                        failure=int(failure or 0),
                        rate=RATES.rate(str(origin), str(target)),
                        avg_latency_ms=int(latency) if latency is not None else None,
                        updated_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            PreviewSourceStatRow.origin_platform,
                            PreviewSourceStatRow.target_platform,
                        ],
                        set_={
                            "success": int(success or 0),
                            "failure": int(failure or 0),
                            "rate": RATES.rate(str(origin), str(target)),
                            "avg_latency_ms": int(latency) if latency is not None else None,
                            "updated_at": now,
                        },
                    )
                )
            await session.execute(
                delete(PreviewEventRow).where(
                    PreviewEventRow.created_at < now - timedelta(days=_EVENT_RETENTION_DAYS)
                )
            )
            await session.commit()
    except Exception as exc:
        log.warning("preview_stats_prewarm_failed", error_type=type(exc).__name__)

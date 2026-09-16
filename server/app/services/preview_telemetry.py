from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.adapters.persistence.models import PreviewEventRow, PreviewSourceStatRow
from app.domain.matching import track_key
from app.domain.models import TrackRef

log = structlog.get_logger(__name__)

_DEFAULT_RATE = 0.5
_MIN_SAMPLES = 3
_STATS_WINDOW_DAYS = 7
_EVENT_RETENTION_DAYS = 30
_DEFAULT_HALF_LIFE_SEC = 259_200.0
_STAT_TIERS = frozenset({"T2", "T3", "T4", "T5", "T6", "T7"})


@dataclass
class _Counts:
    success: float = 0.0
    failure: float = 0.0
    latency_total_ms: float = 0.0
    latency_samples: float = 0.0
    updated_at: float = field(default_factory=time.monotonic)

    @property
    def total(self) -> float:
        return self.success + self.failure

    def decay(self, now: float, half_life_sec: float) -> None:
        elapsed = max(0.0, now - self.updated_at)
        # Sub-second decay only turns exact sample thresholds (for example three
        # fresh failures) into 2.999999 without adding meaningful recency.
        if elapsed >= 1.0 and half_life_sec > 0:
            factor = math.exp2(-elapsed / half_life_sec)
            self.success *= factor
            self.failure *= factor
            self.latency_total_ms *= factor
            self.latency_samples *= factor
        self.updated_at = now

    def rate(self, prior: float) -> float:
        return (self.success + prior * 2.0) / (self.total + 2.0)

    def latency(self, prior_ms: float) -> float:
        if self.latency_samples <= 0:
            return prior_ms
        return self.latency_total_ms / self.latency_samples


class RateStore:
    """Recent playability and attempt cost for each ``(origin, source)`` pair.

    Counts and latency samples decay toward their priors, so a transient outage
    cannot permanently bury a recovered source. Plain target ids are the legacy
    T2 namespace and retain pair -> target -> global fallback. Other tiers use a
    qualified key and only fall back to the same source across origin platforms.
    """

    def __init__(
        self,
        min_samples: int = _MIN_SAMPLES,
        half_life_sec: float = _DEFAULT_HALF_LIFE_SEC,
    ) -> None:
        self._min_samples = min_samples
        self._half_life_sec = half_life_sec
        self._pairs: dict[tuple[str, str], _Counts] = {}
        self._targets: dict[str, _Counts] = {}
        self._global = _Counts()

    def configure(self, *, half_life_sec: float) -> None:
        self._half_life_sec = half_life_sec

    def record(
        self,
        origin: str,
        target: str,
        ok: bool,
        *,
        samples: float = 1.0,
        latency_ms: int | float | None = None,
        half_life_sec: float | None = None,
    ) -> None:
        if samples <= 0:
            return
        now = time.monotonic()
        half_life = half_life_sec or self._half_life_sec
        for counts in (
            self._pairs.setdefault((origin, target), _Counts()),
            self._targets.setdefault(target, _Counts()),
            self._global,
        ):
            counts.decay(now, half_life)
            if ok:
                counts.success += samples
            else:
                counts.failure += samples
            if latency_ms is not None and latency_ms >= 0:
                counts.latency_total_ms += float(latency_ms) * samples
                counts.latency_samples += samples

    def rate(
        self,
        origin: str,
        target: str,
        *,
        prior: float = _DEFAULT_RATE,
        half_life_sec: float | None = None,
    ) -> float:
        half_life = half_life_sec or self._half_life_sec
        for counts in self._fallback_counts(origin, target):
            if counts is None:
                continue
            counts.decay(time.monotonic(), half_life)
            if counts.total >= self._min_samples:
                return counts.rate(prior)
        return prior

    def target_rate(self, target: str) -> float:
        """Return the learned playability of a target without an origin platform."""
        fallback = (
            (self._targets.get(target), self._global)
            if ":" not in target
            else (self._targets.get(target),)
        )
        for counts in fallback:
            if counts is None:
                continue
            counts.decay(time.monotonic(), self._half_life_sec)
            if counts.total >= self._min_samples:
                return counts.rate(_DEFAULT_RATE)
        return _DEFAULT_RATE

    def latency(
        self,
        origin: str,
        target: str,
        *,
        prior: float,
        half_life_sec: float | None = None,
    ) -> float:
        half_life = half_life_sec or self._half_life_sec
        prior_ms = max(0.0, prior * 1000.0)
        for counts in self._fallback_counts(origin, target):
            if counts is None:
                continue
            counts.decay(time.monotonic(), half_life)
            if counts.latency_samples >= self._min_samples:
                return counts.latency(prior_ms) / 1000.0
        return prior_ms / 1000.0

    def samples(
        self,
        origin: str,
        target: str,
        *,
        half_life_sec: float | None = None,
    ) -> float:
        counts = self._pairs.get((origin, target)) or self._targets.get(target)
        if counts is None:
            return 0.0
        counts.decay(time.monotonic(), half_life_sec or self._half_life_sec)
        return counts.total

    def total_samples(self, *, half_life_sec: float | None = None) -> float:
        self._global.decay(time.monotonic(), half_life_sec or self._half_life_sec)
        return self._global.total

    def _fallback_counts(self, origin: str, target: str) -> tuple[_Counts | None, ...]:
        pair = self._pairs.get((origin, target))
        target_counts = self._targets.get(target)
        if ":" in target:
            return pair, target_counts
        return pair, target_counts, self._global

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


def source_stat_key(tier: str, source_id: str) -> str | None:
    """Map stable tier semantics to an isolated statistics namespace."""
    if tier == "T2":
        return source_id
    if tier == "T3":
        return f"download:{source_id}"
    if tier in {"T4", "T5", "T6"}:
        return f"clip:{source_id}"
    if tier == "T7":
        return f"fuzzy:{source_id}"
    return None


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
    stat_key = (
        source_stat_key(event.tier, event.source_platform)
        if event.source_platform is not None
        else None
    )
    if stat_key is not None and not event.cached:
        RATES.record(
            event.track.platform,
            stat_key,
            event.status == "ok",
            latency_ms=event.latency_ms,
        )
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


async def prewarm(
    session_factory: object,
    *,
    half_life_sec: float = _DEFAULT_HALF_LIFE_SEC,
) -> None:
    """Seed the rate store from recent events and refresh the aggregate table."""
    RATES.configure(half_life_sec=half_life_sec)
    since = datetime.now(UTC) - timedelta(days=_STATS_WINDOW_DAYS)
    try:
        async with session_factory() as session:  # type: ignore[operator]
            result = await session.execute(
                select(
                    PreviewEventRow.origin_platform,
                    PreviewEventRow.tier,
                    PreviewEventRow.source_platform,
                    PreviewEventRow.status,
                    PreviewEventRow.latency_ms,
                    PreviewEventRow.created_at,
                )
                .where(
                    PreviewEventRow.created_at >= since,
                    PreviewEventRow.tier.in_(_STAT_TIERS),
                    PreviewEventRow.source_platform.is_not(None),
                )
            )
            now = datetime.now(UTC)
            aggregates: dict[tuple[str, str], list[float]] = {}
            for origin, tier, source, status, latency, created_at in result.all():
                if source is None:
                    continue
                key = source_stat_key(str(tier), str(source))
                if key is None:
                    continue
                observed_at = created_at
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=UTC)
                age_sec = max(0.0, (now - observed_at).total_seconds())
                weight = math.exp2(-age_sec / half_life_sec)
                RATES.record(
                    str(origin),
                    key,
                    str(status) == "ok",
                    samples=weight,
                    latency_ms=int(latency) if latency is not None else None,
                    half_life_sec=half_life_sec,
                )
                aggregate = aggregates.setdefault((str(origin), key), [0.0, 0.0, 0.0, 0.0])
                if str(status) == "ok":
                    aggregate[0] += 1
                else:
                    aggregate[1] += 1
                if latency is not None:
                    aggregate[2] += int(latency)
                    aggregate[3] += 1
            for (origin, target), (success, failure, latency_total, latency_count) in (
                aggregates.items()
            ):
                avg_latency = int(latency_total / latency_count) if latency_count else None
                await session.execute(
                    pg_insert(PreviewSourceStatRow)
                    .values(
                        origin_platform=str(origin),
                        target_platform=str(target),
                        success=int(success or 0),
                        failure=int(failure or 0),
                        rate=RATES.rate(
                            str(origin), str(target), half_life_sec=half_life_sec
                        ),
                        avg_latency_ms=avg_latency,
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
                            "rate": RATES.rate(
                                str(origin), str(target), half_life_sec=half_life_sec
                            ),
                            "avg_latency_ms": avg_latency,
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

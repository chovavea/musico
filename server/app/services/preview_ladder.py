from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from app.services.preview_telemetry import RATES, RateStore


class SourceKind(StrEnum):
    """Stable source categories; callers only rank sources from one category."""

    CROSS_OFFICIAL = "cross_official"
    DOWNLOAD = "download"
    CLIP = "clip"
    FUZZY_CLIP = "fuzzy_clip"


@dataclass(frozen=True)
class KindProfile:
    """Cold-start estimates shared only by providers in the same category."""

    prior_playability: float
    prior_latency_sec: float


_BASE_PROFILES = {
    SourceKind.CROSS_OFFICIAL: KindProfile(0.55, 1.5),
    SourceKind.DOWNLOAD: KindProfile(0.35, 3.0),
    SourceKind.CLIP: KindProfile(0.5, 2.0),
    SourceKind.FUZZY_CLIP: KindProfile(0.45, 2.0),
}


@dataclass(frozen=True)
class AdaptiveTuning:
    """Small set of runtime knobs for recency and exploration."""

    explore_weight: float = 0.08
    half_life_sec: float = 259_200.0

    @classmethod
    def from_settings(cls, settings: object) -> AdaptiveTuning:
        return cls(
            explore_weight=float(getattr(settings, "preview_explore_weight", 0.08)),
            half_life_sec=float(
                getattr(settings, "preview_decay_half_life_sec", 259_200.0)
            ),
        )

    def profile(self, kind: SourceKind) -> KindProfile:
        return _BASE_PROFILES[kind]


@dataclass(frozen=True)
class PreviewSource:
    """One provider the ladder can ask, plus its deterministic cold order.

    ``order_index`` is the position the source would have had under the fixed
    ladder (a download source's configured priority, or the order the listen
    sites are declared in). It only decides ties.
    """

    source_id: str
    kind: SourceKind
    tier: str
    order_index: int

    @property
    def stat_key(self) -> str:
        if self.kind is SourceKind.CROSS_OFFICIAL:
            return self.source_id
        if self.kind is SourceKind.DOWNLOAD:
            return f"download:{self.source_id}"
        if self.kind is SourceKind.CLIP:
            return f"clip:{self.source_id}"
        return f"fuzzy:{self.source_id}"


@dataclass(frozen=True)
class SourceScore:
    """Why a source sits where it does; kept for logs and tests."""

    source_id: str
    expected_cost_sec: float
    playability: float
    optimistic_playability: float
    latency_sec: float
    samples: float

    @property
    def total(self) -> float:
        """Compatibility/debug score: larger is better."""
        return -self.expected_cost_sec


def score_source(
    source: PreviewSource,
    origin_platform: str,
    *,
    rates: RateStore = RATES,
    tuning: AdaptiveTuning | None = None,
) -> SourceScore:
    """Estimate the time paid for one successful result from this provider.

    For serial alternatives with equal semantic value, ordering by ``time / P``
    minimizes expected time to the first success. A bounded UCB bonus keeps new
    or recovered providers observable without allowing a lower-trust category
    to jump ahead: mixed categories are rejected by ``order_sources``.
    """
    tuning = tuning or AdaptiveTuning()
    profile = tuning.profile(source.kind)
    playability = rates.rate(
        origin_platform,
        source.stat_key,
        prior=profile.prior_playability,
        half_life_sec=tuning.half_life_sec,
    )
    latency = rates.latency(
        origin_platform,
        source.stat_key,
        prior=profile.prior_latency_sec,
        half_life_sec=tuning.half_life_sec,
    )
    samples = rates.samples(
        origin_platform, source.stat_key, half_life_sec=tuning.half_life_sec
    )
    curiosity = tuning.explore_weight * math.sqrt(
        math.log(rates.total_samples(half_life_sec=tuning.half_life_sec) + 2.0)
        / (samples + 1.0)
    )
    optimistic = min(0.99, max(0.05, playability + curiosity))
    return SourceScore(
        source_id=source.source_id,
        expected_cost_sec=max(0.001, latency) / optimistic,
        playability=playability,
        optimistic_playability=optimistic,
        latency_sec=latency,
        samples=samples,
    )


def order_sources(
    sources: list[PreviewSource],
    origin_platform: str,
    *,
    rates: RateStore = RATES,
    tuning: AdaptiveTuning | None = None,
    adaptive: bool = True,
) -> list[PreviewSource]:
    """Rank one category; the fixed ladder is the cold-start tie-break order.

    The HTTP layer asks providers in this order and may hedge a second source
    after a delay. Mixed categories are rejected so a lower-trust tier cannot
    jump ahead.
    """
    kinds = {source.kind for source in sources}
    if len(kinds) > 1:
        raise ValueError("preview source categories must be ordered separately")
    if not adaptive:
        return sorted(sources, key=lambda source: (source.order_index, source.source_id))
    return sorted(
        sources,
        key=lambda source: (
            score_source(
                source, origin_platform, rates=rates, tuning=tuning
            ).expected_cost_sec,
            source.order_index,
            source.source_id,
        ),
    )

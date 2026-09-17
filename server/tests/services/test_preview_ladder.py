from __future__ import annotations

import pytest
from app.services.preview_ladder import (
    AdaptiveTuning,
    PreviewSource,
    SourceKind,
    order_sources,
    score_source,
)
from app.services.preview_telemetry import RateStore, source_stat_key


def source(
    source_id: str,
    *,
    kind: SourceKind = SourceKind.CLIP,
    order_index: int = 0,
    tier: str | None = None,
) -> PreviewSource:
    return PreviewSource(
        source_id=source_id,
        kind=kind,
        tier=tier or ("T3" if kind is SourceKind.DOWNLOAD else "T4"),
        order_index=order_index,
    )


def test_cold_start_keeps_the_deterministic_provider_order() -> None:
    rates = RateStore()
    providers = [
        source("gequbao", order_index=2),
        source("sonoma", order_index=0),
        source("flmp3", order_index=1),
    ]

    assert [
        item.source_id for item in order_sources(providers, "origin", rates=rates)
    ] == ["sonoma", "flmp3", "gequbao"]


def test_playability_and_attempt_latency_reorder_one_category() -> None:
    rates = RateStore(min_samples=1)
    for _ in range(4):
        rates.record("origin", "clip:slow", True, latency_ms=4_000)
        rates.record("origin", "clip:fast", True, latency_ms=200)

    ordered = order_sources(
        [source("slow", order_index=0), source("fast", order_index=1)],
        "origin",
        rates=rates,
    )

    assert [item.source_id for item in ordered] == ["fast", "slow"]


def test_recent_failures_decay_back_toward_the_cold_prior() -> None:
    rates = RateStore(min_samples=1)
    for _ in range(4):
        rates.record("origin", "clip:sonoma", False, latency_ms=5_000)
    assert rates.rate("origin", "clip:sonoma", prior=0.5) < 0.5

    for counts in (
        rates._pairs[("origin", "clip:sonoma")],
        rates._targets["clip:sonoma"],
        rates._global,
    ):
        counts.updated_at -= 100.0

    assert rates.rate(
        "origin", "clip:sonoma", prior=0.5, half_life_sec=1.0
    ) == pytest.approx(0.5)


def test_ucb_bonus_keeps_an_untried_source_observable() -> None:
    rates = RateStore(min_samples=1)
    for _ in range(8):
        rates.record("origin", "clip:known", True, latency_ms=2_000)
    tuning = AdaptiveTuning(explore_weight=0.2)

    untried = score_source(source("new"), "origin", rates=rates, tuning=tuning)
    known = score_source(source("known"), "origin", rates=rates, tuning=tuning)

    assert untried.samples == 0
    assert untried.optimistic_playability > untried.playability
    assert (
        untried.optimistic_playability - untried.playability
        > known.optimistic_playability - known.playability
    )


def test_a_fast_clip_can_outrank_a_slow_download_source() -> None:
    rates = RateStore(min_samples=1)
    for _ in range(4):
        rates.record("origin", "download:ventura", False, latency_ms=1_700)
        rates.record("origin", "clip:gequbao", True, latency_ms=1_000)

    ordered = order_sources(
        [
            source("ventura", kind=SourceKind.DOWNLOAD, order_index=0),
            source("gequbao", kind=SourceKind.CLIP, order_index=1),
        ],
        "origin",
        rates=rates,
    )

    assert [item.source_id for item in ordered] == ["gequbao", "ventura"]


def test_cold_start_expected_cost_puts_clips_ahead_of_download_sources() -> None:
    rates = RateStore()
    ordered = order_sources(
        [
            source("ventura", kind=SourceKind.DOWNLOAD, order_index=0),
            source("gequbao", kind=SourceKind.CLIP, order_index=1),
        ],
        "origin",
        rates=rates,
    )
    assert [item.source_id for item in ordered] == ["gequbao", "ventura"]


def test_disabling_adaptive_order_keeps_the_ladder_index() -> None:
    ordered = order_sources(
        [
            source("gequbao", kind=SourceKind.CLIP, order_index=1),
            source("ventura", kind=SourceKind.DOWNLOAD, order_index=0),
        ],
        "origin",
        adaptive=False,
    )
    assert [item.source_id for item in ordered] == ["ventura", "gequbao"]


def test_legacy_t5_and_t6_events_share_the_t4_clip_namespace() -> None:
    assert source_stat_key("T4", "sonoma") == "clip:sonoma"
    assert source_stat_key("T5", "flmp3") == "clip:flmp3"
    assert source_stat_key("T6", "gequbao") == "clip:gequbao"
    assert source_stat_key("T7", "gequbao") == "fuzzy:gequbao"

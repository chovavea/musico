from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.download_source_circuit import (
    DownloadSourceCircuit,
    next_quota_reset_sec,
)


def test_quota_reset_covers_the_rest_of_the_cst_day() -> None:
    tz = ZoneInfo("Asia/Shanghai")
    remaining = next_quota_reset_sec(wall_now=datetime(2026, 9, 17, 23, 0, tzinfo=tz))
    assert remaining == 3_900.0


def test_quota_reset_after_midnight_waits_for_the_following_day() -> None:
    tz = ZoneInfo("Asia/Shanghai")
    remaining = next_quota_reset_sec(wall_now=datetime(2026, 9, 18, 0, 0, tzinfo=tz))
    assert remaining == 86_700.0


def test_limited_source_is_blocked_until_the_deadline() -> None:
    clock = {"now": 0.0}
    circuit = DownloadSourceCircuit(
        monotonic=lambda: clock["now"],
        open_for_sec=lambda: 10.0,
    )
    assert circuit.allow("ventura")
    circuit.note_limited("ventura")
    assert circuit.is_blocked("ventura")
    assert not circuit.allow("ventura")
    clock["now"] = 9.9
    assert circuit.is_blocked("ventura")


def test_half_open_allows_one_probe_then_reopens_on_quota() -> None:
    clock = {"now": 0.0}
    circuit = DownloadSourceCircuit(
        monotonic=lambda: clock["now"],
        open_for_sec=lambda: 10.0,
    )
    circuit.note_limited("ventura")
    clock["now"] = 10.0
    assert not circuit.is_blocked("ventura")
    assert circuit.allow("ventura")
    assert not circuit.allow("ventura")
    circuit.note_limited("ventura")
    assert circuit.is_blocked("ventura")
    clock["now"] = 19.9
    assert not circuit.allow("ventura")


def test_successful_probe_closes_the_breaker() -> None:
    clock = {"now": 0.0}
    circuit = DownloadSourceCircuit(
        monotonic=lambda: clock["now"],
        open_for_sec=lambda: 10.0,
    )
    circuit.note_limited("ventura")
    clock["now"] = 10.0
    assert circuit.allow("ventura")
    circuit.note_ok("ventura")
    assert circuit.allow("ventura")
    assert not circuit.is_blocked("ventura")


def test_inconclusive_probe_can_be_retried() -> None:
    clock = {"now": 0.0}
    circuit = DownloadSourceCircuit(
        monotonic=lambda: clock["now"],
        open_for_sec=lambda: 10.0,
    )
    circuit.note_limited("ventura")
    clock["now"] = 10.0
    assert circuit.allow("ventura")
    circuit.note_inconclusive("ventura")
    assert circuit.allow("ventura")

from datetime import datetime, timedelta, timezone

from app.services.health import compute_staleness


def test_fresh_within_multiplier() -> None:
    now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    updated = now - timedelta(seconds=3599)
    assert compute_staleness(updated, 1800, 2, now=now) == "fresh"


def test_stale_after_multiplier() -> None:
    now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    updated = now - timedelta(seconds=3601)
    assert compute_staleness(updated, 1800, 2, now=now) == "stale"

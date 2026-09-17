from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Quota pages say "今日"; the sources that emit them run on China Standard Time.
_QUOTA_TZ = ZoneInfo("Asia/Shanghai")
_RECOVERY_GRACE_SEC = 300.0
_MIN_OPEN_SEC = 60.0


def next_quota_reset_sec(
    *,
    wall_now: datetime | None = None,
    tz: ZoneInfo = _QUOTA_TZ,
    grace_sec: float = _RECOVERY_GRACE_SEC,
) -> float:
    """Seconds to keep a source skipped after it reports a daily quota."""
    now = wall_now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(_MIN_OPEN_SEC, (nxt - now).total_seconds() + grace_sec)


@dataclass
class _State:
    open_until: float
    probe_reserved: bool = False


class DownloadSourceCircuit:
    """Skip a download source until its daily quota is expected to reset.

    The breaker is process-local, like ``PreviewCache``. After ``open_until``
    one request may probe; a fresh quota page trips it until the next reset.
    """

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        open_for_sec: Callable[[], float] = next_quota_reset_sec,
    ) -> None:
        self._monotonic = monotonic
        self._open_for_sec = open_for_sec
        self._states: dict[str, _State] = {}

    def is_blocked(self, source_id: str) -> bool:
        """True while the source must not be contacted (half-open probes excluded)."""
        state = self._states.get(source_id)
        if state is None:
            return False
        return self._monotonic() < state.open_until

    def allow(self, source_id: str) -> bool:
        """Reserve a contact. Follow with note_limited, note_ok, or note_inconclusive."""
        state = self._states.get(source_id)
        if state is None:
            return True
        now = self._monotonic()
        if now < state.open_until:
            return False
        if state.probe_reserved:
            return False
        state.probe_reserved = True
        return True

    def note_limited(self, source_id: str) -> None:
        self._states[source_id] = _State(
            open_until=self._monotonic() + self._open_for_sec(),
            probe_reserved=False,
        )

    def note_ok(self, source_id: str) -> None:
        self._states.pop(source_id, None)

    def note_inconclusive(self, source_id: str) -> None:
        """Release a half-open probe that failed for a reason other than quota."""
        state = self._states.get(source_id)
        if state is not None:
            state.probe_reserved = False

    def clear(self) -> None:
        self._states.clear()


CIRCUITS = DownloadSourceCircuit()

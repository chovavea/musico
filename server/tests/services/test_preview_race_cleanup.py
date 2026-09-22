from __future__ import annotations

import asyncio

import pytest
from app.adapters.http.preview import _AttemptResult, _AttemptSpec, _hedged_attempts
from app.domain.models import TrackRef
from app.services.preview_ladder import PreviewSource, SourceKind
from app.services.preview_plan import PreviewPolicy
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse


@pytest.mark.parametrize("priorities", [(0, 0), (0, 1), (1, 0)])
async def test_simultaneous_success_closes_every_losing_response(
    priorities: tuple[int, int],
) -> None:
    ready = asyncio.Event()
    started: list[int] = []
    closed: list[int] = []

    async def close(index: int) -> None:
        closed.append(index)

    def spec(index: int) -> _AttemptSpec:
        async def run() -> _AttemptResult:
            started.append(index)
            if len(started) == 2:
                ready.set()
            await ready.wait()
            return _AttemptResult(
                response=StreamingResponse(
                    iter([b"audio"]), background=BackgroundTask(close, index)
                )
            )

        return _AttemptSpec(
            source=PreviewSource(str(index), SourceKind.CLIP, "T4", index),
            run=run,
            priority=priorities[index],
            hedge_after_sec=0,
        )

    result, winner = await asyncio.wait_for(
        _hedged_attempts(
            [spec(0), spec(1)],
            TrackRef(platform="test", external_id="1", title="Song", artist="Artist"),
            PreviewPolicy(),
            [],
            timeout_error="timeout",
        ),
        timeout=2,
    )
    expected = min(range(2), key=lambda index: (priorities[index], index))
    assert winner is not None and winner.source_id == str(expected)
    assert closed == [1 - expected]
    assert result is not None and result.response is not None
    assert result.response.background is not None
    await result.response.background()
    assert sorted(closed) == [0, 1]

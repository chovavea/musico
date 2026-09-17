from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any
from urllib.parse import urljoin

import httpx
import structlog
from fastapi import Request
from fastapi.responses import StreamingResponse
from mutagen import File as MutagenFile
from starlette.background import BackgroundTask

from app.adapters.http.safety import (
    MAX_HOPS,
    REDIRECT_STATUSES,
    assert_outbound_url_allowed,
    headers_for_redirect,
    host_matches,
)
from app.domain.matching import (
    is_fuzzy_listen_match,
    is_incomplete_listen_duration,
    is_listen_match,
)
from app.domain.models import DownloadCandidate, TrackRef
from app.download_sources.protocol import DownloadSourceAccessLimited
from app.download_sources.registry import DownloadSourceRecord, DownloadSourceRegistry
from app.plugins._registry import PluginRecord, PluginRegistry
from app.services.download_source_circuit import CIRCUITS
from app.services.preview_ladder import (
    PreviewSource,
    SourceKind,
    order_sources,
    score_source,
)
from app.services.preview_plan import PreviewPlanner, PreviewPolicy, PreviewTarget
from app.services.preview_telemetry import (
    CACHE,
    CachedTarget,
    PreviewEvent,
    cache_key,
    publish,
)

log = structlog.get_logger(__name__)

_ALLOWED_SUFFIXES = (
    "music.163.com",
    "music.126.net",
    "qqmusic.qq.com",
    "tc.qq.com",
    "bilivideo.com",
    "bilivideo.cn",
    "kugou.com",
    "kuwo.cn",
)
# Upstream calls are not meant to be cut short: a slow answer is still a usable
# answer, so the only per-call ceiling is a generous one minute. Production reads
# PREVIEW_CALL_TIMEOUT_SEC; this is the fallback when no settings are wired.
_CALL_TIMEOUT_SEC = 60.0

_PASSTHROUGH = (
    "content-length",
    "content-range",
    "accept-ranges",
    "cache-control",
)
# Enough of a file for mutagen to read Xing / Ogg headers before we commit.
_DURATION_PROBE_BYTES = 65_536

# Prefer browser-friendly, smaller files for listening, not the highest download
# quality. DSD and other download-only formats cannot be played by HTMLAudio.
_AUDIO_FORMATS = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "webm": "audio/webm",
    "flac": "audio/flac",
    "wav": "audio/wav",
}

_FORMAT_ORDER = {name: index for index, name in enumerate(_AUDIO_FORMATS)}

# Official preview streams only answer the web player of their own platform.
_PLATFORM_REFERERS = {
    "netease": "https://music.163.com/",
    "qqmusic": "https://y.qq.com/",
    "bilibili": "https://www.bilibili.com/audio/home/",
    "kugou": "https://www.kugou.com/",
    "kuwo": "https://www.kuwo.cn/",
}


@dataclass
class _AttemptResult:
    response: StreamingResponse | None = None
    source_external_id: str | None = None
    match_score: float | None = None
    target: PreviewTarget | None = None
    error: str = "source_unavailable"
    events: list[PreviewEvent] = field(default_factory=list)


@dataclass(frozen=True)
class _AttemptSpec:
    source: PreviewSource
    run: Callable[[], Coroutine[Any, Any, _AttemptResult]]
    priority: int = 0
    hedge_after_sec: float | None = None
    emit_event: bool = True


def host_allowed(host: str) -> bool:
    return host_matches(host, _ALLOWED_SUFFIXES)


def preview_policy(request: Request) -> PreviewPolicy:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        return PreviewPolicy()
    return PreviewPolicy.from_settings(settings)


def preview_call_timeout(request: Request) -> float:
    """Ceiling for one upstream call (search, URL parse or opening the stream)."""
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        return _CALL_TIMEOUT_SEC
    return float(getattr(settings, "preview_call_timeout_sec", _CALL_TIMEOUT_SEC))


async def stream_preview(
    request: Request,
    track: TrackRef,
    *,
    download_only: bool = False,
) -> StreamingResponse:
    """Serve a listening stream through official tiers, then an adaptive pool.

    T1 and T2 stay preferred: a faster download or clip cannot replace an
    in-flight official preview. After T1 starts, T2 may hedge; after T2
    starts, the T3/T4 pool may hedge. Official success cancels the rest.
    Fuzzy clips (T7) stay last.
    """
    client: httpx.AsyncClient = request.app.state.preview_client
    registry: PluginRegistry = request.app.state.registry
    range_header = request.headers.get("range")
    policy = preview_policy(request)
    call_timeout = preview_call_timeout(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    started = time.monotonic()
    events: list[PreviewEvent] = []
    has_metadata = bool(track.title.strip() and track.artist.strip())

    specs: list[_AttemptSpec] = []
    if not download_only:
        specs.append(
            _official_attempt_spec(
                client, registry, track, range_header, call_timeout, policy
            )
        )
        if policy.cross_platform:
            specs.append(
                _cross_platform_ladder_spec(
                    client, registry, track, range_header, policy, call_timeout
                )
            )
    if has_metadata:
        specs.extend(
            _fallback_attempt_specs(
                request,
                client,
                request.app.state.download_sources,
                track,
                range_header,
                call_timeout,
                policy,
                include_clips=not download_only,
            )
        )
    elif download_only:
        events.append(
            PreviewEvent(
                track=track,
                tier="none",
                status="error",
                error="track_metadata_missing",
            )
        )
        empty = StreamingResponse(iter(()), status_code=404)
        return await _finish(empty, events, started, session_factory)

    result, _winning_source = await _hedged_attempts(
        specs,
        track,
        policy,
        events,
        timeout_error=(
            "download_deadline_exceeded" if download_only else "preview_deadline_exceeded"
        ),
    )
    if result is not None and result.response is not None:
        return await _finish(result.response, events, started, session_factory)

    if not has_metadata:
        events.append(
            PreviewEvent(
                track=track,
                tier="none",
                status="error",
                error="track_metadata_missing",
            )
        )
        empty = StreamingResponse(iter(()), status_code=404)
        return await _finish(empty, events, started, session_factory)

    if not download_only:
        result, _winning_source = await _hedged_attempts(
            _listen_attempt_specs(
                client,
                _ordered_listen_clip_providers(
                    request, track, policy, fuzzy=True
                ),
                track,
                range_header,
                call_timeout,
                fuzzy=True,
            ),
            track,
            policy,
            events,
            timeout_error="listen_deadline_exceeded",
        )
        if result is not None and result.response is not None:
            return await _finish(result.response, events, started, session_factory)
    events.append(
        PreviewEvent(
            track=track,
            tier="none",
            status="error",
            error="download_unavailable" if download_only else "no_source",
        )
    )
    empty = StreamingResponse(iter(()), status_code=404)
    return await _finish(empty, events, started, session_factory)


async def _finish(
    response: StreamingResponse,
    events: list[PreviewEvent],
    started: float,
    session_factory: object | None,
) -> StreamingResponse:
    total_latency_ms = int((time.monotonic() - started) * 1000)
    for event in events:
        if event.latency_ms is None:
            event.latency_ms = total_latency_ms
    # Diagnostics must not sit between the click and the first audio byte, so the
    # writes start immediately but the response is not held back for them.
    async def _publish_all() -> None:
        for event in events:
            await publish(event, session_factory=session_factory)

    task = asyncio.create_task(_publish_all())
    task.add_done_callback(_log_publish_failure)
    prior = response.background

    async def _finalize() -> None:
        try:
            await task
        finally:
            if prior is not None:
                await prior()

    response.background = BackgroundTask(_finalize)
    return response


def _log_publish_failure(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:  # pragma: no cover - publish already swallows DB errors
        log.warning("preview_event_write_failed", error_type=type(error).__name__)


def _attempt_event(
    track: TrackRef,
    tier: str,
    source_id: str,
    started: float,
    *,
    ok: bool,
    source_external_id: str | None = None,
    match_score: float | None = None,
    error: str | None = None,
) -> PreviewEvent:
    return PreviewEvent(
        track=track,
        tier=tier,
        status="ok" if ok else "error",
        source_platform=source_id,
        source_external_id=source_external_id,
        match_score=match_score,
        error=None if ok else error,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def _hedge_delay(source: PreviewSource, track: TrackRef, policy: PreviewPolicy) -> float:
    estimate = score_source(
        source,
        track.platform,
        tuning=policy.adaptive_tuning(),
    ).latency_sec
    return min(
        policy.hedge_max_delay_sec,
        max(policy.hedge_min_delay_sec, estimate * 0.75),
    )


def _spec_hedge_delay(spec: _AttemptSpec, track: TrackRef, policy: PreviewPolicy) -> float:
    if spec.hedge_after_sec is not None:
        return spec.hedge_after_sec
    return _hedge_delay(spec.source, track, policy)


def _emit_attempt(
    events: list[PreviewEvent],
    track: TrackRef,
    spec: _AttemptSpec,
    started: float,
    result: _AttemptResult,
    *,
    ok: bool,
) -> None:
    if not spec.emit_event:
        events.extend(result.events)
        return
    events.append(
        _attempt_event(
            track,
            spec.source.tier,
            spec.source.source_id,
            started,
            ok=ok,
            source_external_id=result.source_external_id if ok else None,
            match_score=result.match_score if ok else None,
            error=None if ok else result.error,
        )
    )


async def _discard_response(response: StreamingResponse) -> None:
    if response.background is not None:
        await response.background()


async def _cancel_attempts(
    running: dict[asyncio.Task[_AttemptResult], tuple[_AttemptSpec, float, int]],
) -> None:
    tasks = list(running)
    for task in tasks:
        task.cancel()
    if tasks:
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, _AttemptResult) and outcome.response is not None:
                await _discard_response(outcome.response)
    running.clear()


async def _hedged_attempts(
    specs: list[_AttemptSpec],
    track: TrackRef,
    policy: PreviewPolicy,
    events: list[PreviewEvent],
    *,
    timeout_error: str,
) -> tuple[_AttemptResult | None, PreviewSource | None]:
    """Run ordered providers with a delayed hedge.

    A success cancels worse-priority work. Lower-priority audio is held until
    every better-priority attempt has finished, so a clip cannot beat an
    in-flight official preview. Same-priority providers still race: the first
    playable stream wins.
    """
    if not specs:
        return None, None
    running: dict[asyncio.Task[_AttemptResult], tuple[_AttemptSpec, float, int]] = {}
    next_index = 0
    next_launch_at = 0.0
    held: tuple[_AttemptResult, _AttemptSpec, float] | None = None

    def has_better_outstanding(priority: int) -> bool:
        if any(spec.priority < priority for spec, _started, _index in running.values()):
            return True
        return any(spec.priority < priority for spec in specs[next_index:])

    def should_skip_launch(spec: _AttemptSpec) -> bool:
        return held is not None and spec.priority >= held[1].priority

    def launch() -> None:
        nonlocal next_index, next_launch_at
        while next_index < len(specs) and should_skip_launch(specs[next_index]):
            next_index += 1
        if next_index >= len(specs):
            return
        spec = specs[next_index]
        started = time.monotonic()
        task: asyncio.Task[_AttemptResult] = asyncio.create_task(spec.run())
        running[task] = (spec, started, next_index)
        next_index += 1
        next_launch_at = started + _spec_hedge_delay(spec, track, policy)

    def cancel_worse(priority: int) -> None:
        for task, (spec, _started, _index) in list(running.items()):
            if spec.priority >= priority:
                task.cancel()

    def commit_held() -> tuple[_AttemptResult, PreviewSource]:
        assert held is not None
        result, spec, started = held
        _emit_attempt(events, track, spec, started, result, ok=True)
        return result, spec.source

    launch()
    try:
        while running or held is not None:
            if not running:
                if held is not None and not has_better_outstanding(held[1].priority):
                    return commit_held()
                launch()
                if not running:
                    return commit_held() if held is not None else (None, None)
                continue

            wait_timeout: float | None = None
            if (
                policy.hedge_enabled
                and next_index < len(specs)
                and len(running) < 2
                and not should_skip_launch(specs[next_index])
            ):
                wait_timeout = max(0.0, next_launch_at - time.monotonic())
            done, _pending = await asyncio.wait(
                running,
                timeout=wait_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                launch()
                continue

            completed: list[tuple[int, _AttemptSpec, float, _AttemptResult, bool]] = []
            for task in done:
                spec, started, index = running.pop(task)
                cancelled = False
                try:
                    result = task.result()
                except asyncio.CancelledError:
                    result = _AttemptResult(error=timeout_error)
                    cancelled = True
                except Exception as exc:
                    result = _AttemptResult(error=type(exc).__name__)
                completed.append((index, spec, started, result, cancelled))
            completed.sort(key=lambda item: item[0])

            for _index, spec, started, result, cancelled in completed:
                if cancelled:
                    if result.response is not None:
                        await _discard_response(result.response)
                    continue
                if result.response is not None:
                    cancel_worse(spec.priority)
                    if held is not None and spec.priority < held[1].priority:
                        if held[0].response is not None:
                            await _discard_response(held[0].response)
                        held = None
                    elif held is not None:
                        await _discard_response(result.response)
                        continue
                    held = result, spec, started
                    if not has_better_outstanding(spec.priority):
                        return commit_held()
                else:
                    _emit_attempt(events, track, spec, started, result, ok=False)

            if held is not None and not has_better_outstanding(held[1].priority):
                return commit_held()
            if next_index < len(specs) and len(running) < 2:
                launch()
        return commit_held() if held is not None else (None, None)
    except asyncio.CancelledError:
        if held is not None and held[0].response is not None:
            await _discard_response(held[0].response)
            held = None
        for _task, (spec, started, _index) in running.items():
            if spec.emit_event:
                events.append(
                    _attempt_event(
                        track,
                        spec.source.tier,
                        spec.source.source_id,
                        started,
                        ok=False,
                        error=timeout_error,
                    )
                )
        raise
    finally:
        await _cancel_attempts(running)


_PRIORITY_OFFICIAL = 0
_PRIORITY_CROSS = 1
_PRIORITY_FALLBACK = 2


def _official_attempt_spec(
    client: httpx.AsyncClient,
    registry: PluginRegistry,
    track: TrackRef,
    range_header: str | None,
    timeout: float,
    policy: PreviewPolicy,
) -> _AttemptSpec:
    descriptor = PreviewSource(
        source_id=track.platform,
        kind=SourceKind.OFFICIAL,
        tier="T1",
        order_index=0,
    )

    async def run() -> _AttemptResult:
        response, error = await _official_stream(
            client, registry, track, range_header, timeout
        )
        if response is not None:
            return _AttemptResult(
                response=response,
                source_external_id=track.external_id,
            )
        return _AttemptResult(error=error or "official_unavailable")

    return _AttemptSpec(
        source=descriptor,
        run=run,
        priority=_PRIORITY_OFFICIAL,
        hedge_after_sec=policy.hedge_min_delay_sec,
    )


def _cross_platform_ladder_spec(
    client: httpx.AsyncClient,
    registry: PluginRegistry,
    track: TrackRef,
    range_header: str | None,
    policy: PreviewPolicy,
    timeout: float,
) -> _AttemptSpec:
    descriptor = PreviewSource(
        source_id="cross_official",
        kind=SourceKind.CROSS_OFFICIAL,
        tier="T2",
        order_index=1,
    )

    async def run() -> _AttemptResult:
        response, target, cached, attempts = await _cross_platform_stream(
            client, registry, track, range_header, policy, None, timeout
        )
        if response is not None and target is not None:
            extra = list(attempts)
            if cached:
                extra.append(
                    PreviewEvent(
                        track=track,
                        tier="T2",
                        status="ok",
                        source_platform=target.platform,
                        source_external_id=target.external_id,
                        match_score=target.match_score,
                        cached=True,
                    )
                )
            return _AttemptResult(
                response=response,
                source_external_id=target.external_id,
                match_score=target.match_score,
                target=target,
                events=extra,
            )
        return _AttemptResult(error="cross_platform_unavailable", events=attempts)

    return _AttemptSpec(
        source=descriptor,
        run=run,
        priority=_PRIORITY_CROSS,
        hedge_after_sec=policy.hedge_min_delay_sec,
        emit_event=False,
    )


async def _official_stream(
    client: httpx.AsyncClient,
    registry: PluginRegistry,
    track: TrackRef,
    range_header: str | None,
    timeout: float,
) -> tuple[StreamingResponse | None, str | None]:
    record = registry.get(track.platform)
    if record is None or record.preview is None:
        return None, "official_unavailable"
    try:
        async with asyncio.timeout(timeout):
            info = await record.preview.preview(track)
            if not info.preview_url:
                return None, "official_unavailable"
            response = await _open_audio(
                client,
                info.preview_url,
                _referer_headers(track.platform),
                _ALLOWED_SUFFIXES,
                range_header=range_header,
                media_type="audio/mp4" if track.platform == "bilibili" else "audio/mpeg",
                expected_duration_ms=track.duration_ms,
                require_complete=True,
            )
            if response is None:
                return None, "official_unavailable"
            return response, None
    except Exception as exc:
        # Upstream exception messages can contain signed media URLs.
        error_type = type(exc).__name__
        log.info("official_preview_unavailable", error_type=error_type)
        return None, error_type


async def _cross_platform_stream(
    client: httpx.AsyncClient,
    registry: PluginRegistry,
    track: TrackRef,
    range_header: str | None,
    policy: PreviewPolicy,
    _session_factory: object | None = None,
    timeout: float = _CALL_TIMEOUT_SEC,
) -> tuple[
    StreamingResponse | None,
    PreviewTarget | None,
    bool,
    list[PreviewEvent],
]:
    key = cache_key(track)
    if CACHE.negative(key):
        return None, None, False, []
    cached = CACHE.positive(key)
    if cached is not None:
        response = await _open_target(
            client, cached.platform, cached.url, range_header, timeout, track.duration_ms
        )
        if response is not None:
            return response, _cached_target(track, cached), True, []
        # The stored URL is a signed link that expires before the entry does;
        # forgetting it here keeps later clicks from paying for the same dead
        # open before falling back to a fresh search.
        CACHE.invalidate_positive(key)
    attempts: list[PreviewEvent] = []
    planner = PreviewPlanner(track, registry, policy)
    timed_out = False
    result: _AttemptResult | None = None
    try:
        async with asyncio.timeout(policy.deadline_sec):
            result, _winner = await _hedged_attempts(
                _cross_platform_attempt_specs(
                    client, planner, track, range_header, timeout
                ),
                track,
                policy,
                attempts,
                timeout_error="cross_platform_deadline_exceeded",
            )
    except TimeoutError:
        timed_out = True
        log.info(
            "cross_platform_deadline_exceeded",
            origin_platform=track.platform,
            platform=planner.current_platform,
        )
    if result is not None and result.response is not None and result.target is not None:
        played = result.target
        CACHE.store_positive(
            key,
            CachedTarget(
                platform=played.platform,
                external_id=played.external_id,
                url=played.url,
                match_score=played.match_score,
            ),
            policy.positive_ttl_sec,
        )
        return result.response, played, False, attempts
    if not timed_out and (planner.searched or planner.attempted):
        # Nothing on the other platform is playable right now: remember briefly
        # instead of re-querying every platform on the next click. A deadline that
        # ran out mid-ladder proves nothing, so it is not remembered that way.
        CACHE.store_negative(key, policy.negative_ttl_sec)
    return None, None, False, attempts


def _cached_target(track: TrackRef, cached: CachedTarget) -> PreviewTarget:
    return PreviewTarget(
        platform=cached.platform,
        external_id=cached.external_id,
        title=track.title,
        artist=track.artist,
        url=cached.url,
        match_score=cached.match_score or 0.0,
        rate=0.0,
        search_rank=0,
        quality_rank=0,
    )


async def _open_target(
    client: httpx.AsyncClient,
    platform: str,
    url: str,
    range_header: str | None,
    timeout: float,
    expected_duration_ms: int | None,
) -> StreamingResponse | None:
    try:
        async with asyncio.timeout(timeout):
            return await _open_audio(
                client,
                url,
                _referer_headers(platform),
                _ALLOWED_SUFFIXES,
                range_header=range_header,
                media_type="audio/mpeg",
                expected_duration_ms=expected_duration_ms,
                require_complete=True,
            )
    except Exception as exc:
        log.info(
            "cross_platform_preview_unavailable",
            platform=platform,
            error_type=type(exc).__name__,
        )
        return None


def _referer_headers(platform: str) -> dict[str, str]:
    referer = _PLATFORM_REFERERS.get(platform)
    return {"Referer": referer} if referer else {}


async def _try_cross_platform_provider(
    client: httpx.AsyncClient,
    planner: PreviewPlanner,
    record: PluginRecord,
    range_header: str | None,
    timeout: float,
) -> _AttemptResult:
    async for candidate in planner.iter_provider_targets(record):
        planner.attempted = True
        response = await _open_target(
            client,
            candidate.platform,
            candidate.url,
            range_header,
            timeout,
            planner.track.duration_ms,
        )
        if response is not None:
            return _AttemptResult(
                response=response,
                source_external_id=candidate.external_id,
                match_score=candidate.match_score,
                target=candidate,
            )
    return _AttemptResult(error="cross_platform_unavailable")


def _cross_platform_attempt_specs(
    client: httpx.AsyncClient,
    planner: PreviewPlanner,
    track: TrackRef,
    range_header: str | None,
    timeout: float,
) -> list[_AttemptSpec]:
    specs: list[_AttemptSpec] = []
    for index, record in enumerate(planner.providers):
        descriptor = PreviewSource(
            source_id=record.plugin_id,
            kind=SourceKind.CROSS_OFFICIAL,
            tier="T2",
            order_index=index,
        )

        async def run(current: PluginRecord = record) -> _AttemptResult:
            return await _try_cross_platform_provider(
                client, planner, current, range_header, timeout
            )

        specs.append(_AttemptSpec(source=descriptor, run=run))
    return specs


def _enabled_download_sources(
    sources: DownloadSourceRegistry,
) -> list[DownloadSourceRecord]:
    # An empty manifest allowlist must not turn this into a public URL proxy.
    return [
        source
        for source in sources.enabled()
        if source.hosts and not CIRCUITS.is_blocked(source.source_id)
    ]


def _fallback_attempt_specs(
    request: Request,
    client: httpx.AsyncClient,
    sources: DownloadSourceRegistry,
    track: TrackRef,
    range_header: str | None,
    timeout: float,
    policy: PreviewPolicy,
    *,
    include_clips: bool,
) -> list[_AttemptSpec]:
    """Rank download sources and strict clips together by expected time-to-audio."""
    downloads = _enabled_download_sources(sources)
    combined = _download_attempt_specs(
        client,
        downloads,
        track,
        range_header,
        timeout,
        priority=_PRIORITY_FALLBACK,
    )
    if include_clips:
        clips = _listen_clip_providers(request)
        combined.extend(
            _listen_attempt_specs(
                client,
                clips,
                track,
                range_header,
                timeout,
                fuzzy=False,
                order_start=len(combined),
                priority=_PRIORITY_FALLBACK,
            )
        )
    ranked = order_sources(
        [spec.source for spec in combined],
        track.platform,
        tuning=policy.adaptive_tuning(),
        adaptive=policy.adaptive_order,
    )
    by_key = {(spec.source.kind, spec.source.source_id): spec for spec in combined}
    return [by_key[(item.kind, item.source_id)] for item in ranked]


async def _download_source_candidates(
    source: DownloadSourceRecord,
    track: TrackRef,
    timeout: float,
) -> AsyncIterator[DownloadCandidate]:
    """Search and rank candidates from exactly one download source."""
    if not CIRCUITS.allow(source.source_id):
        return
    try:
        async with asyncio.timeout(timeout):
            found = await source.source.search(track)
    except DownloadSourceAccessLimited:
        CIRCUITS.note_limited(source.source_id)
        log.warning("preview_search_access_limited", source_id=source.source_id)
        return
    except Exception as exc:
        CIRCUITS.note_inconclusive(source.source_id)
        log.info(
            "preview_search_unavailable",
            source_id=source.source_id,
            error_type=type(exc).__name__,
        )
        return
    CIRCUITS.note_ok(source.source_id)
    for candidate in _rank_candidates(source, found, track):
        yield candidate


async def _try_download_source(
    client: httpx.AsyncClient,
    source: DownloadSourceRecord,
    track: TrackRef,
    range_header: str | None,
    timeout: float,
) -> _AttemptResult:
    async for candidate in _download_source_candidates(source, track, timeout):
        try:
            async with asyncio.timeout(timeout):
                resolved = await source.source.resolve(candidate)
                response = await _open_audio(
                    client,
                    resolved.url,
                    resolved.headers,
                    source.hosts,
                    range_header=range_header,
                    media_type=_AUDIO_FORMATS[
                        candidate.quality.format.lower().lstrip(".")
                    ],
                    expected_duration_ms=track.duration_ms,
                    require_complete=True,
                )
        except DownloadSourceAccessLimited:
            CIRCUITS.note_limited(source.source_id)
            log.warning("download_preview_access_limited", source_id=source.source_id)
            return _AttemptResult(error="download_access_limited")
        except Exception as exc:
            log.info(
                "download_preview_unavailable",
                source_id=source.source_id,
                error_type=type(exc).__name__,
            )
            continue
        if response is not None:
            return _AttemptResult(
                response=response,
                source_external_id=candidate.source_track_id,
            )
    return _AttemptResult(error="download_unavailable")


def _download_attempt_specs(
    client: httpx.AsyncClient,
    sources: list[DownloadSourceRecord],
    track: TrackRef,
    range_header: str | None,
    timeout: float,
    *,
    priority: int = 0,
) -> list[_AttemptSpec]:
    specs: list[_AttemptSpec] = []
    for index, source in enumerate(sources):
        descriptor = PreviewSource(
            source_id=source.source_id,
            kind=SourceKind.DOWNLOAD,
            tier="T3",
            order_index=index,
        )

        async def run(current: DownloadSourceRecord = source) -> _AttemptResult:
            return await _try_download_source(
                client, current, track, range_header, timeout
            )

        specs.append(_AttemptSpec(source=descriptor, run=run, priority=priority))
    return specs


def _rank_candidates(
    source: DownloadSourceRecord, found: list[DownloadCandidate], track: TrackRef
) -> list[DownloadCandidate]:
    """Keep what matches the track and can play in a browser, lightest first."""
    matching = [
        candidate
        for candidate in found
        if candidate.source_id == source.source_id
        and candidate.quality.format.lower().lstrip(".") in _AUDIO_FORMATS
        and is_listen_match(track, _candidate_ref(candidate))
    ]
    matching.sort(
        key=lambda candidate: (
            _FORMAT_ORDER[candidate.quality.format.lower().lstrip(".")],
            candidate.quality.sample_rate_hz or 0,
            candidate.quality.bit_depth or 0,
        )
    )
    return matching


def _listen_clip_providers(request: Request) -> list[tuple[str, object]]:
    providers: list[tuple[str, object]] = []
    fallback = getattr(request.app.state, "fallback_service", None)
    iterate = getattr(fallback, "iter_preview_clips", None) if fallback is not None else None
    if iterate is not None:
        providers.append(("sonoma", iterate))
    flmp3 = getattr(request.app.state, "flmp3_preview", None)
    iterate = getattr(flmp3, "iter_preview_clips", None) if flmp3 is not None else None
    if iterate is not None:
        providers.append(("flmp3", iterate))
    gequbao = getattr(request.app.state, "gequbao_preview", None)
    iterate = getattr(gequbao, "iter_preview_clips", None) if gequbao is not None else None
    if iterate is not None:
        providers.append(("gequbao", iterate))
    return providers


def _ordered_listen_clip_providers(
    request: Request,
    track: TrackRef,
    policy: PreviewPolicy,
    *,
    fuzzy: bool,
) -> list[tuple[str, object]]:
    providers = _listen_clip_providers(request)
    by_id = dict(providers)
    kind = SourceKind.FUZZY_CLIP if fuzzy else SourceKind.CLIP
    ranked = order_sources(
        [
            PreviewSource(
                source_id=source_id,
                kind=kind,
                tier="T7" if fuzzy else "T4",
                order_index=index,
            )
            for index, (source_id, _iterate) in enumerate(providers)
        ],
        track.platform,
        tuning=policy.adaptive_tuning(),
        adaptive=policy.adaptive_order,
    )
    return [(source.source_id, by_id[source.source_id]) for source in ranked]


def _listen_attempt_specs(
    client: httpx.AsyncClient,
    providers: list[tuple[str, object]],
    track: TrackRef,
    range_header: str | None,
    timeout: float,
    *,
    fuzzy: bool,
    order_start: int = 0,
    priority: int = 0,
) -> list[_AttemptSpec]:
    kind = SourceKind.FUZZY_CLIP if fuzzy else SourceKind.CLIP
    tier = "T7" if fuzzy else "T4"
    specs: list[_AttemptSpec] = []
    for index, (source_id, iterate) in enumerate(providers):
        descriptor = PreviewSource(
            source_id=source_id,
            kind=kind,
            tier=tier,
            order_index=order_start + index,
        )

        async def run(
            current_id: str = source_id,
            current_iterate: object = iterate,
        ) -> _AttemptResult:
            response, clip_id = await _play_listen_clips(
                client,
                current_iterate,
                track,
                range_header,
                timeout,
                current_id,
                match=is_fuzzy_listen_match if fuzzy else is_listen_match,
            )
            return _AttemptResult(
                response=response,
                source_external_id=clip_id,
                error=f"{current_id}_unavailable",
            )

        specs.append(_AttemptSpec(source=descriptor, run=run, priority=priority))
    return specs


async def _play_listen_clips(
    client: httpx.AsyncClient,
    iterate: object,
    track: TrackRef,
    range_header: str | None,
    timeout: float,
    source_id: str,
    *,
    match: object | None = None,
) -> tuple[StreamingResponse | None, str | None]:
    try:
        iterate_kw = {} if match is None else {"match": match}
        async for clip in iterate(track, **iterate_kw):  # type: ignore[operator]
            try:
                async with asyncio.timeout(timeout):
                    response = await _open_audio(
                        client,
                        clip.url,
                        {"Referer": clip.referer},
                        clip.allowed_hosts,
                        range_header=range_header,
                        media_type=clip.media_type,
                        expected_duration_ms=track.duration_ms,
                        require_complete=True,
                    )
            except Exception as exc:
                log.info(
                    "listen_clip_unavailable",
                    source_id=source_id,
                    error_type=type(exc).__name__,
                )
                continue
            if response is not None:
                return response, clip.source_track_id
    except Exception as exc:
        log.info(
            "listen_clip_search_unavailable",
            source_id=source_id,
            error_type=type(exc).__name__,
        )
    return None, None


def _candidate_ref(candidate: DownloadCandidate) -> TrackRef:
    return TrackRef(
        platform=candidate.source_id,
        external_id=candidate.source_track_id,
        title=candidate.title,
        artist=candidate.artist,
        album=candidate.album,
        duration_ms=candidate.duration_ms,
        isrc=candidate.isrc,
        version=candidate.version,
    )


async def _open_audio(
    client: httpx.AsyncClient,
    url: str,
    source_headers: dict[str, str],
    allowed_hosts: tuple[str, ...],
    *,
    range_header: str | None,
    media_type: str,
    expected_duration_ms: int | None = None,
    require_complete: bool = False,
) -> StreamingResponse | None:
    headers = httpx.Headers(source_headers)
    headers.pop("host", None)
    headers.pop("range", None)
    headers["Accept-Encoding"] = "identity"
    if range_header:
        headers["Range"] = range_header
    upstream: httpx.Response | None = None
    try:
        for _hop in range(MAX_HOPS):
            await assert_outbound_url_allowed(url, allowed_hosts)
            upstream = await client.send(
                client.build_request("GET", url, headers=headers),
                stream=True,
                follow_redirects=False,
            )
            if upstream.status_code not in REDIRECT_STATUSES:
                break
            location = upstream.headers.get("location")
            await upstream.aclose()
            if not location:
                return None
            next_url = urljoin(str(upstream.url), location)
            headers = httpx.Headers(headers_for_redirect(dict(headers), url, next_url))
            url = next_url
        else:
            return None

        if upstream is None or upstream.status_code not in {200, 206}:
            if upstream is not None:
                await upstream.aclose()
            return None
        content_type = upstream.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("audio/"):
            if content_type == "video/mp4" and media_type == "audio/mp4":
                # Bilibili's official player endpoint serves an MP4 container even
                # when the stream is used as an audio-only preview.
                content_type = media_type
            elif content_type not in {"", "application/octet-stream", "binary/octet-stream"}:
                await upstream.aclose()
                return None
            else:
                content_type = media_type

        # Check the first bytes before committing response headers, so an empty
        # file, a disguised error page or an early network failure can fall back.
        body = upstream.aiter_bytes()
        first = await anext(body, b"")
        starts_at_zero = upstream.status_code == 200 or upstream.headers.get(
            "content-range", ""
        ).lower().startswith("bytes 0-")
        if not first or (starts_at_zero and first.lstrip().startswith((b"<", b"{"))):
            await upstream.aclose()
            return None
        if require_complete and expected_duration_ms and starts_at_zero:
            gathered = [first]
            size = len(first)
            async for piece in body:
                gathered.append(piece)
                size += len(piece)
                if size >= _DURATION_PROBE_BYTES:
                    break
            first = b"".join(gathered)
            stream_ms = _audio_duration_ms(first)
            if is_incomplete_listen_duration(expected_duration_ms, stream_ms):
                log.info(
                    "preview_incomplete_snippet",
                    stream_ms=stream_ms,
                    expected_ms=expected_duration_ms,
                )
                await upstream.aclose()
                return None
    except BaseException:
        if upstream is not None:
            await upstream.aclose()
        raise

    async def chunks() -> AsyncIterator[bytes]:
        try:
            yield first
            async for chunk in body:
                yield chunk
        finally:
            await upstream.aclose()

    out_headers = {
        name: value for name, value in upstream.headers.items() if name.lower() in _PASSTHROUGH
    }
    if upstream.headers.get("content-encoding"):
        # aiter_bytes decodes content encodings; the original length no longer applies.
        out_headers.pop("content-length", None)
    return StreamingResponse(
        chunks(),
        status_code=upstream.status_code,
        media_type=content_type,
        headers=out_headers,
        background=BackgroundTask(upstream.aclose),
    )


def _audio_duration_ms(header: bytes) -> int | None:
    """Best-effort duration from the start of a stream. Unknown is not a reject."""
    if len(header) < 16:
        return None
    try:
        parsed = MutagenFile(BytesIO(header))
    except Exception:
        return None
    length = getattr(getattr(parsed, "info", None), "length", None)
    if not isinstance(length, int | float) or length <= 0:
        return None
    return int(length * 1000)

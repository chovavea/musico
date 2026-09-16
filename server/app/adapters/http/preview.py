from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
import structlog
from fastapi import Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.adapters.http.safety import (
    MAX_HOPS,
    REDIRECT_STATUSES,
    assert_outbound_url_allowed,
    headers_for_redirect,
    host_matches,
)
from app.domain.matching import is_auto_match, is_fuzzy_preview_match
from app.domain.models import DownloadCandidate, TrackRef
from app.download_sources.registry import DownloadSourceRecord, DownloadSourceRegistry
from app.plugins._registry import PluginRecord, PluginRegistry
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


@dataclass(frozen=True)
class _AttemptSpec:
    source: PreviewSource
    run: Callable[[], Coroutine[Any, Any, _AttemptResult]]


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
    """Serve a listening stream through fixed trust tiers and adaptive providers.

    Tier order never changes: T1 own official, T2 cross-platform official, T3
    download sources, T4 strict in-page clips, then T7 fuzzy clips. Providers
    inside T2/T3/T4/T7 are ranked from recent playability and first-byte cost.
    Within a tier the first provider starts immediately; a second may hedge
    after a short delay. The first playable stream wins and the rest stop.
    """
    client: httpx.AsyncClient = request.app.state.preview_client
    registry: PluginRegistry = request.app.state.registry
    range_header = request.headers.get("range")
    policy = preview_policy(request)
    call_timeout = preview_call_timeout(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    started = time.monotonic()
    events: list[PreviewEvent] = []

    if not download_only:
        response = await _official_stream(client, registry, track, range_header, call_timeout)
        if response is not None:
            events.append(
                PreviewEvent(
                    track=track,
                    tier="T1",
                    status="ok",
                    source_platform=track.platform,
                    source_external_id=track.external_id,
                )
            )
            return await _finish(response, events, started, session_factory)

        if policy.cross_platform:
            response, target, cached, attempts = await _cross_platform_stream(
                client, registry, track, range_header, policy, session_factory, call_timeout
            )
            events.extend(attempts)
            if response is not None and target is not None:
                if cached:
                    events.append(
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
                return await _finish(response, events, started, session_factory)

    # Old stream URLs without metadata remain usable for official previews.
    # Never search by an opaque platform id or accidentally match an empty song.
    if not track.title.strip() or not track.artist.strip():
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

    sources: DownloadSourceRegistry = request.app.state.download_sources
    result, _winning_source = await _hedged_attempts(
        _download_attempt_specs(
            client,
            _ordered_download_sources(sources, track, policy),
            track,
            range_header,
            call_timeout,
        ),
        track,
        policy,
        events,
        timeout_error="download_deadline_exceeded",
    )
    if result is not None and result.response is not None:
        return await _finish(result.response, events, started, session_factory)

    if not download_only:
        for fuzzy in (False, True):
            result, _winning_source = await _hedged_attempts(
                _listen_attempt_specs(
                    client,
                    _ordered_listen_clip_providers(
                        request, track, policy, fuzzy=fuzzy
                    ),
                    track,
                    range_header,
                    call_timeout,
                    fuzzy=fuzzy,
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
    """Run ordered providers with one delayed hedge and return the first audio."""
    if not specs:
        return None, None
    running: dict[asyncio.Task[_AttemptResult], tuple[_AttemptSpec, float, int]] = {}
    next_index = 0
    next_launch_at = 0.0

    def launch() -> None:
        nonlocal next_index, next_launch_at
        spec = specs[next_index]
        started = time.monotonic()
        task: asyncio.Task[_AttemptResult] = asyncio.create_task(spec.run())
        running[task] = (spec, started, next_index)
        next_index += 1
        next_launch_at = started + _hedge_delay(spec.source, track, policy)

    launch()
    try:
        while running:
            wait_timeout: float | None = None
            if (
                policy.hedge_enabled
                and next_index < len(specs)
                and len(running) < 2
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

            completed: list[tuple[int, _AttemptSpec, float, _AttemptResult]] = []
            for task in done:
                spec, started, index = running.pop(task)
                try:
                    result = task.result()
                except asyncio.CancelledError:
                    result = _AttemptResult(error=timeout_error)
                except Exception as exc:
                    result = _AttemptResult(error=type(exc).__name__)
                completed.append((index, spec, started, result))
            completed.sort(key=lambda item: item[0])

            winner: tuple[_AttemptResult, PreviewSource] | None = None
            for _index, spec, started, result in completed:
                if result.response is not None and winner is None:
                    events.append(
                        _attempt_event(
                            track,
                            spec.source.tier,
                            spec.source.source_id,
                            started,
                            ok=True,
                            source_external_id=result.source_external_id,
                            match_score=result.match_score,
                        )
                    )
                    winner = result, spec.source
                elif result.response is not None:
                    await _discard_response(result.response)
                else:
                    events.append(
                        _attempt_event(
                            track,
                            spec.source.tier,
                            spec.source.source_id,
                            started,
                            ok=False,
                            error=result.error,
                        )
                    )
            if winner is not None:
                return winner

            if next_index < len(specs) and len(running) < 2:
                # A known failure should not wait for the hedge timer.
                launch()
        return None, None
    except asyncio.CancelledError:
        for _task, (spec, started, _index) in running.items():
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


async def _official_stream(
    client: httpx.AsyncClient,
    registry: PluginRegistry,
    track: TrackRef,
    range_header: str | None,
    timeout: float,
) -> StreamingResponse | None:
    record = registry.get(track.platform)
    if record is None or record.preview is None:
        return None
    try:
        async with asyncio.timeout(timeout):
            info = await record.preview.preview(track)
            if not info.preview_url:
                return None
            return await _open_audio(
                client,
                info.preview_url,
                _referer_headers(track.platform),
                _ALLOWED_SUFFIXES,
                range_header=range_header,
                media_type="audio/mp4" if track.platform == "bilibili" else "audio/mpeg",
            )
    except Exception as exc:
        # Upstream exception messages can contain signed media URLs.
        log.info("official_preview_unavailable", error_type=type(exc).__name__)
        return None


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
        response = await _open_target(client, cached.platform, cached.url, range_header, timeout)
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
            client, candidate.platform, candidate.url, range_header, timeout
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


def _ordered_download_sources(
    sources: DownloadSourceRegistry,
    track: TrackRef,
    policy: PreviewPolicy,
) -> list[DownloadSourceRecord]:
    # An empty manifest allowlist must not turn this into a public URL proxy.
    enabled = [source for source in sources.enabled() if source.hosts]
    by_id = {source.source_id: source for source in enabled}
    ranked = order_sources(
        [
            PreviewSource(
                source_id=source.source_id,
                kind=SourceKind.DOWNLOAD,
                tier="T3",
                order_index=index,
            )
            for index, source in enumerate(enabled)
        ],
        track.platform,
        tuning=policy.adaptive_tuning(),
        adaptive=policy.adaptive_order,
    )
    return [by_id[source.source_id] for source in ranked]


async def _download_source_candidates(
    source: DownloadSourceRecord,
    track: TrackRef,
    timeout: float,
) -> AsyncIterator[DownloadCandidate]:
    """Search and rank candidates from exactly one download source."""
    try:
        async with asyncio.timeout(timeout):
            found = await source.source.search(track)
    except Exception as exc:
        log.info(
            "preview_search_unavailable",
            source_id=source.source_id,
            error_type=type(exc).__name__,
        )
        return
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
                )
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

        specs.append(_AttemptSpec(source=descriptor, run=run))
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
        and is_auto_match(track, _candidate_ref(candidate))
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
) -> list[_AttemptSpec]:
    kind = SourceKind.FUZZY_CLIP if fuzzy else SourceKind.CLIP
    tier = "T7" if fuzzy else "T4"
    specs: list[_AttemptSpec] = []
    for index, (source_id, iterate) in enumerate(providers):
        descriptor = PreviewSource(
            source_id=source_id,
            kind=kind,
            tier=tier,
            order_index=index,
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
                match=is_fuzzy_preview_match if fuzzy else None,
            )
            return _AttemptResult(
                response=response,
                source_external_id=clip_id,
                error=f"{current_id}_unavailable",
            )

        specs.append(_AttemptSpec(source=descriptor, run=run))
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

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
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
from app.domain.matching import is_auto_match
from app.domain.models import DownloadCandidate, TrackRef
from app.download_sources.registry import DownloadSourceRecord, DownloadSourceRegistry
from app.plugins._registry import PluginRegistry
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
}


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
    """Serve a listening stream: local tier is chosen by the client.

    Order is fixed and each tier only runs when the previous one produced no
    playable stream: T1 the track's own official preview, T2 another platform's
    official preview, T3 the configured download sources (preview only, no
    download task is created). Every step is serial: neither the next platform
    nor the next download source is contacted until the current one failed to
    play, so a single click never fans out into parallel upstream requests.
    """
    client: httpx.AsyncClient = request.app.state.preview_client
    registry: PluginRegistry = request.app.state.registry
    range_header = request.headers.get("range")
    policy = preview_policy(request)
    call_timeout = preview_call_timeout(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    started = time.monotonic()
    event = PreviewEvent(track=track, tier="none", status="error", error="no_source")

    if not download_only:
        response = await _official_stream(client, registry, track, range_header, call_timeout)
        if response is not None:
            event.tier = "T1"
            event.source_platform = track.platform
            event.source_external_id = track.external_id
            return await _finish(response, event, started, session_factory)

        if policy.cross_platform:
            response, target, cached = await _cross_platform_stream(
                client, registry, track, range_header, policy, session_factory, call_timeout
            )
            if response is not None and target is not None:
                event.tier, event.match_score = "T2", target.match_score
                event.source_platform = target.platform
                event.source_external_id = target.external_id
                event.cached = cached
                return await _finish(response, event, started, session_factory)
            event.error = "cross_platform_unavailable"
        else:
            event.error = "official_unavailable"

    # Old stream URLs without metadata remain usable for official previews.
    # Never search by an opaque platform id or accidentally match an empty song.
    if not track.title.strip() or not track.artist.strip():
        event.error = "track_metadata_missing"
        empty = StreamingResponse(iter(()), status_code=404)
        return await _finish(empty, event, started, session_factory)

    sources: DownloadSourceRegistry = request.app.state.download_sources
    async for source, candidate in _download_candidates(sources, track, call_timeout):
        try:
            async with asyncio.timeout(call_timeout):
                resolved = await source.source.resolve(candidate)
                response = await _open_audio(
                    client,
                    resolved.url,
                    resolved.headers,
                    source.hosts,
                    range_header=range_header,
                    media_type=_AUDIO_FORMATS[candidate.quality.format.lower().lstrip(".")],
                )
                if response is not None:
                    event.tier = "T3"
                    event.source_platform = source.source_id
                    event.source_external_id = candidate.source_track_id
                    return await _finish(response, event, started, session_factory)
        except Exception as exc:
            log.info(
                "download_preview_unavailable",
                source_id=source.source_id,
                error_type=type(exc).__name__,
            )
    event.error = "download_unavailable"
    empty = StreamingResponse(iter(()), status_code=404)
    return await _finish(empty, event, started, session_factory)


async def _finish(
    response: StreamingResponse,
    event: PreviewEvent,
    started: float,
    session_factory: object | None,
) -> StreamingResponse:
    event.latency_ms = int((time.monotonic() - started) * 1000)
    if event.tier != "none":
        event.status, event.error = "ok", None
    # Diagnostics must not sit between the click and the first audio byte, so the
    # write starts immediately but the response is not held back for it. The audit
    # task is chained into the response background: it is awaited once the body is
    # done so a failure is still visible, while a client that walks away mid-track
    # leaves its row behind instead of losing it with the request.
    task = asyncio.create_task(publish(event, session_factory=session_factory))
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
    session_factory: object | None = None,
    timeout: float = _CALL_TIMEOUT_SEC,
) -> tuple[StreamingResponse | None, PreviewTarget | None, bool]:
    key = cache_key(track)
    if CACHE.negative(key):
        return None, None, False
    response: StreamingResponse | None = None
    played: PreviewTarget | None = None
    cached = CACHE.positive(key)
    if cached is not None:
        response = await _open_target(client, cached.platform, cached.url, range_header, timeout)
        if response is not None:
            return response, _cached_target(track, cached), True
        # The stored URL is a signed link that expires before the entry does;
        # forgetting it here keeps later clicks from paying for the same dead
        # open before falling back to a fresh search.
        CACHE.invalidate_positive(key)
    planner = PreviewPlanner(track, registry, policy)
    error = "cross_platform_unavailable"
    timed_out = False
    try:
        # One platform at a time: the next search only happens after the current
        # one produced nothing that could be played.
        async with asyncio.timeout(policy.deadline_sec):
            async for candidate in planner.iter_targets():
                response = await _open_target(
                    client, candidate.platform, candidate.url, range_header, timeout
                )
                if response is not None:
                    played = candidate
                    break
    except TimeoutError:
        timed_out = True
        error = "cross_platform_deadline_exceeded"
        log.info(
            "cross_platform_deadline_exceeded",
            origin_platform=track.platform,
            platform=planner.current_platform,
        )
    # A platform that was asked and served nothing is evidence against that pair;
    # without it the next click would keep ranking a dead combination by its
    # cold-start prior. Searches that raised are skipped on purpose: a timeout or
    # a network hiccup must not demote a platform that normally works.
    for platform_id in planner.contacted:
        if played is not None and platform_id == played.platform:
            continue
        await publish(
            PreviewEvent(
                track=track,
                tier="T2",
                status="error",
                source_platform=platform_id,
                error=error,
            ),
            session_factory=session_factory,
        )
    if played is not None and response is not None:
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
        return response, played, False
    if not timed_out and (planner.searched or planner.attempted):
        # Nothing on the other platform is playable right now: remember briefly
        # instead of re-querying every platform on the next click. A deadline that
        # ran out mid-ladder proves nothing, so it is not remembered that way.
        CACHE.store_negative(key, policy.negative_ttl_sec)
    return None, None, False


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


async def _download_candidates(
    sources: DownloadSourceRegistry, track: TrackRef, timeout: float
) -> AsyncIterator[tuple[DownloadSourceRecord, DownloadCandidate]]:
    """Walk the download sources one at a time, highest priority first.

    A source is only searched after every source before it failed to produce
    playable audio, so this tier never fans out into parallel upstream requests.
    """
    # An empty manifest allowlist must not turn this into a public URL proxy.
    enabled = [source for source in sources.enabled() if source.hosts]
    for source in enabled:
        try:
            async with asyncio.timeout(timeout):
                found = await source.source.search(track)
        except Exception as exc:
            log.info(
                "preview_search_unavailable",
                source_id=source.source_id,
                error_type=type(exc).__name__,
            )
            continue
        for candidate in _rank_candidates(source, found, track):
            yield source, candidate


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

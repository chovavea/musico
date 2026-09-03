from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse

from app.domain.models import TrackRef

_ALLOWED_SUFFIXES = (
    "music.163.com",
    "music.126.net",
    "qqmusic.qq.com",
    "tc.qq.com",
)

_PASSTHROUGH = (
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "cache-control",
)


def host_allowed(host: str) -> bool:
    cleaned = host.lower().rstrip(".")
    return any(cleaned == suffix or cleaned.endswith(f".{suffix}") for suffix in _ALLOWED_SUFFIXES)


async def stream_official_preview(
    request: Request,
    platform: str,
    external_id: str,
) -> StreamingResponse:
    registry = request.app.state.registry
    client: httpx.AsyncClient = request.app.state.http_client
    record = registry.get(platform)
    if record is None or record.preview is None:
        return StreamingResponse(iter(()), status_code=404)
    info = await record.preview.preview(
        TrackRef(
            platform=platform,
            external_id=external_id,
            title="preview",
            artist="preview",
        )
    )
    if not info.preview_url:
        return StreamingResponse(iter(()), status_code=404)
    parsed = httpx.URL(info.preview_url)
    if not host_allowed(parsed.host or ""):
        return StreamingResponse(iter(()), status_code=404)
    headers: dict[str, str] = {}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header
    if platform == "netease":
        headers["Referer"] = "https://music.163.com/"
    elif platform == "qqmusic":
        headers["Referer"] = "https://y.qq.com"
    upstream = await client.send(
        client.build_request("GET", info.preview_url, headers=headers),
        stream=True,
    )
    if upstream.status_code >= 400:
        await upstream.aclose()
        return StreamingResponse(iter(()), status_code=404)
    content_type = upstream.headers.get("content-type", "audio/mpeg")
    if content_type.startswith("text/html"):
        await upstream.aclose()
        return StreamingResponse(iter(()), status_code=404)

    async def chunks() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes(64 * 1024):
                yield chunk
        finally:
            await upstream.aclose()

    out_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in _PASSTHROUGH
    }
    return StreamingResponse(
        chunks(),
        status_code=upstream.status_code,
        media_type=content_type,
        headers=out_headers,
    )

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from app.adapters.http import cover
from app.adapters.http.routes import build_router
from fastapi import FastAPI

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg"
PNG = b"\x89PNG\r\n\x1a\n" + b"png"
WEBP = b"RIFF\x04\x00\x00\x00WEBP"


@pytest.mark.parametrize(
    ("url", "size", "expected"),
    [
        (
            "https://y.gtimg.cn/music/photo_new/T002R300x300M000abc.jpg",
            150,
            "https://y.gtimg.cn/music/photo_new/T002R150x150M000abc.jpg",
        ),
        (
            "https://p1.music.126.net/abc/image.jpg?foo=1&param=99y99",
            500,
            "https://p1.music.126.net/abc/image.jpg?foo=1&param=500y500",
        ),
        (
            "http://p1.music.126.net/abc/image.jpg",
            150,
            "https://p1.music.126.net/abc/image.jpg?param=150y150",
        ),
        (
            "https://i0.hdslb.com/bfs/music/abc.jpg@200w_200h.webp",
            150,
            "https://i0.hdslb.com/bfs/music/abc.jpg@150w_150h_1c.webp",
        ),
    ],
)
def test_rewrite_cover_url_for_each_provider(url: str, size: int, expected: str) -> None:
    assert cover.rewrite_cover_url(url, size) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://y.gtimg.cn:444/music/photo_new/T002R300x300M000abc.jpg",
        "http://y.gtimg.cn:8080/music/photo_new/T002R300x300M000abc.jpg",
        "https://user:pass@y.gtimg.cn/music/photo_new/T002R300x300M000abc.jpg",
        "https://y.gtimg.cn/music/photo_new/T002R300x300M000abc.jpg#fragment",
        "https://evil.example/music/photo_new/T002R300x300M000abc.jpg",
        "https://y.gtimg.cn/not-music/T002R300x300M000abc.jpg",
        "https://y.gtimg.cn/music/photo_new/../private/T002R300x300M000abc.jpg",
        "https://i0.hdslb.com/not-bfs/abc.jpg",
        f"https://p1.music.126.net/{'a' * 2050}.jpg",
    ],
)
def test_rewrite_cover_url_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(cover.CoverImageError):
        cover.rewrite_cover_url(url, 150)


def test_rewrite_cover_url_rejects_unsupported_size() -> None:
    with pytest.raises(cover.CoverImageError, match="150 or 500"):
        cover.rewrite_cover_url("https://p1.music.126.net/image.jpg", 300)


async def test_cover_follows_validated_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    visited: list[str] = []
    validated: list[str] = []

    async def allow(url: str) -> None:
        validated.append(url)

    def upstream(request: httpx.Request) -> httpx.Response:
        visited.append(str(request.url))
        if request.url.host == "y.gtimg.cn":
            return httpx.Response(
                302,
                headers={"Location": "https://p1.music.126.net/final.jpg?param=150y150"},
            )
        return httpx.Response(200, content=JPEG, headers={"Content-Type": "image/jpeg"})

    monkeypatch.setattr(cover, "validate_cover_url", allow)
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        body, media_type = await cover._fetch_image(
            client,
            "https://y.gtimg.cn/music/photo_new/T002R150x150M000abc.jpg",
        )

    assert body == JPEG
    assert media_type == "image/jpeg"
    assert validated == visited


@pytest.mark.parametrize(
    ("body", "content_type"),
    [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")],
)
async def test_cover_accepts_supported_type_with_matching_magic(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    content_type: str,
) -> None:
    async def allow(_url: str) -> None:
        return None

    monkeypatch.setattr(cover, "validate_cover_url", allow)
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=body,
            headers={"Content-Type": content_type},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        fetched, fetched_type = await cover._fetch_image(
            client, "https://p1.music.126.net/image.jpg"
        )
    assert fetched == body
    assert fetched_type == content_type


async def test_cover_normalizes_jpeg_content_type_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow(_url: str) -> None:
        return None

    monkeypatch.setattr(cover, "validate_cover_url", allow)
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=JPEG,
            headers={"Content-Type": "image/jpg"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        fetched, fetched_type = await cover._fetch_image(
            client, "https://p1.music.126.net/image.jpg"
        )
    assert fetched == JPEG
    assert fetched_type == "image/jpeg"


async def test_cover_rejects_more_than_three_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow(_url: str) -> None:
        return None

    def upstream(request: httpx.Request) -> httpx.Response:
        hop = int(request.url.params.get("hop", "0"))
        return httpx.Response(
            302,
            headers={"Location": f"https://p1.music.126.net/image.jpg?hop={hop + 1}"},
        )

    monkeypatch.setattr(cover, "validate_cover_url", allow)
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        with pytest.raises(cover.CoverImageError, match="too many"):
            await cover._fetch_image(client, "https://p1.music.126.net/image.jpg?hop=0")


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (JPEG, "image/png"),
        (b"<html>not an image</html>", "image/jpeg"),
        (PNG, "text/plain"),
        (WEBP, "application/octet-stream"),
    ],
)
async def test_cover_requires_supported_matching_type_and_magic(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    content_type: str,
) -> None:
    async def allow(_url: str) -> None:
        return None

    monkeypatch.setattr(cover, "validate_cover_url", allow)
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=body,
            headers={"Content-Type": content_type},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(cover.CoverImageError):
            await cover._fetch_image(client, "https://p1.music.126.net/image.jpg")


class OversizedStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"\xff\xd8\xff"
        yield b"x" * cover.MAX_IMAGE_BYTES


async def test_cover_stops_when_stream_exceeds_two_mib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow(_url: str) -> None:
        return None

    monkeypatch.setattr(cover, "validate_cover_url", allow)
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            stream=OversizedStream(),
            headers={"Content-Type": "image/jpeg"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(cover.CoverImageError, match="too large"):
            await cover._fetch_image(client, "https://p1.music.126.net/image.jpg")


async def test_cover_endpoint_caches_and_returns_304(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def allow(_url: str) -> None:
        return None

    def upstream(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})

    monkeypatch.setattr(cover, "validate_cover_url", allow)
    monkeypatch.setattr(cover, "CACHE", cover.CoverImageCache())
    app = FastAPI()
    app.include_router(build_router())
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_client:
        app.state.cover_client = upstream_client
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            params = {
                "url": "https://p1.music.126.net/image.jpg?param=99y99",
                "size": "500",
            }
            first = await client.get("/api/v1/cover-image", params=params)
            assert first.status_code == 200, first.text
            second = await client.get("/api/v1/cover-image", params=params)
            not_modified = await client.get(
                "/api/v1/cover-image",
                params=params,
                headers={"If-None-Match": first.headers["etag"]},
            )

    assert first.status_code == 200
    assert first.content == PNG
    assert first.headers["content-type"] == "image/png"
    assert first.headers["cache-control"] == "public, max-age=86400"
    assert first.headers["x-content-type-options"] == "nosniff"
    assert second.content == PNG
    assert not_modified.status_code == 304
    assert not_modified.content == b""
    assert calls == 1


def test_cover_cache_is_lru_byte_and_item_bounded() -> None:
    cache = cover.CoverImageCache(max_bytes=6, max_items=2, ttl_sec=10)
    cache.store("a", b"aaa", "image/png", '"a"', now=0)
    cache.store("b", b"bbb", "image/png", '"b"', now=0)
    assert cache.get("a", now=1) is not None
    cache.store("c", b"ccc", "image/png", '"c"', now=1)

    assert cache.get("a", now=2) is not None
    assert cache.get("b", now=2) is None
    assert cache.get("c", now=12) is None

from __future__ import annotations

import hashlib
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import ParseResult, parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

import httpx
from fastapi import Request
from fastapi.responses import Response

from app.adapters.http.safety import (
    REDIRECT_STATUSES,
    OutboundUrlError,
    assert_outbound_url_allowed,
    headers_for_redirect,
    host_matches,
)

MAX_URL_LENGTH = 2048
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
CACHE_MAX_BYTES = 64 * 1024 * 1024
CACHE_MAX_ITEMS = 512
CACHE_TTL_SEC = 24 * 60 * 60
ALLOWED_SIZES = (150, 500)

_ALLOWED_HOST_SUFFIXES = ("y.gtimg.cn", "music.126.net", "hdslb.com")
_BILIBILI_HOSTS = {"i0.hdslb.com", "i1.hdslb.com", "i2.hdslb.com"}
_QQ_SIZE = re.compile(r"R\d+x\d+", flags=re.IGNORECASE)
_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MEDIA_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/x-png": "image/png",
    "image/x-webp": "image/webp",
}
_RESPONSE_HEADERS = {
    "Cache-Control": f"public, max-age={CACHE_TTL_SEC}",
    "X-Content-Type-Options": "nosniff",
}


class CoverImageError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class CachedImage:
    body: bytes
    media_type: str
    etag: str
    expires_at: float


class CoverImageCache:
    """Independent byte-bounded LRU for fully validated image responses."""

    def __init__(
        self,
        *,
        max_bytes: int = CACHE_MAX_BYTES,
        max_items: int = CACHE_MAX_ITEMS,
        ttl_sec: float = CACHE_TTL_SEC,
    ) -> None:
        self.max_bytes = max_bytes
        self.max_items = max_items
        self.ttl_sec = ttl_sec
        self._items: OrderedDict[str, CachedImage] = OrderedDict()
        self._bytes = 0

    def get(self, key: str, *, now: float | None = None) -> CachedImage | None:
        current = time.monotonic() if now is None else now
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at <= current:
            self._remove(key)
            return None
        self._items.move_to_end(key)
        return entry

    def store(
        self,
        key: str,
        body: bytes,
        media_type: str,
        etag: str,
        *,
        now: float | None = None,
    ) -> None:
        if len(body) > self.max_bytes or self.max_items <= 0:
            return
        if key in self._items:
            self._remove(key)
        current = time.monotonic() if now is None else now
        self._items[key] = CachedImage(
            body=body,
            media_type=media_type,
            etag=etag,
            expires_at=current + self.ttl_sec,
        )
        self._bytes += len(body)
        while len(self._items) > self.max_items or self._bytes > self.max_bytes:
            _oldest, _entry = self._items.popitem(last=False)
            self._bytes -= len(_entry.body)

    def _remove(self, key: str) -> None:
        entry = self._items.pop(key, None)
        if entry is not None:
            self._bytes -= len(entry.body)


CACHE = CoverImageCache()


def rewrite_cover_url(url: str, size: int) -> str:
    """Validate URL shape and force the provider's supported square image size."""
    parsed, host = _parse_allowed_url(url)
    if size not in ALLOWED_SIZES:
        raise CoverImageError("cover size must be 150 or 500")

    if host == "y.gtimg.cn":
        resized, count = _QQ_SIZE.subn(f"R{size}x{size}", parsed.path, count=1)
        if count != 1:
            raise CoverImageError("QQ cover URL has no size marker")
        parsed = parsed._replace(path=resized)
    elif host_matches(host, ("music.126.net",)):
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["param"] = f"{size}y{size}"
        parsed = parsed._replace(query=urlencode(query))
    else:
        base_path = parsed.path.split("@", 1)[0]
        parsed = parsed._replace(path=f"{base_path}@{size}w_{size}h_1c.webp")

    rewritten = urlunparse(parsed)
    if len(rewritten) > MAX_URL_LENGTH:
        raise CoverImageError("cover URL is too long")
    return rewritten


async def validate_cover_url(url: str) -> None:
    """Run strict provider/path checks plus the shared public-IP SSRF guard."""
    _parsed, _host = _parse_allowed_url(url)
    try:
        await assert_outbound_url_allowed(url, _ALLOWED_HOST_SUFFIXES)
    except OutboundUrlError as exc:
        raise CoverImageError(str(exc)) from exc


async def cover_image_response(request: Request, url: str, size: int) -> Response:
    try:
        rewritten = rewrite_cover_url(url, size)
        cached = CACHE.get(rewritten)
        if cached is None:
            client: httpx.AsyncClient = request.app.state.cover_client
            body, media_type = await _fetch_image(client, rewritten)
            etag = f'"{hashlib.sha256(body).hexdigest()}"'
            CACHE.store(rewritten, body, media_type, etag)
            cached = CachedImage(
                body=body,
                media_type=media_type,
                etag=etag,
                expires_at=time.monotonic() + CACHE_TTL_SEC,
            )
        headers = {**_RESPONSE_HEADERS, "ETag": cached.etag}
        if _etag_matches(request.headers.get("if-none-match"), cached.etag):
            return Response(status_code=304, headers=headers)
        return Response(
            content=cached.body,
            media_type=cached.media_type,
            headers=headers,
        )
    except CoverImageError as exc:
        return Response(str(exc), status_code=exc.status_code, media_type="text/plain")
    except httpx.HTTPError:
        return Response("cover upstream request failed", status_code=502, media_type="text/plain")


async def _fetch_image(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
    headers = httpx.Headers(
        {
            "Accept": "image/avif,image/webp,image/png,image/jpeg",
            "Accept-Encoding": "identity",
        }
    )
    upstream: httpx.Response | None = None
    try:
        for redirect_count in range(MAX_REDIRECTS + 1):
            await validate_cover_url(url)
            upstream = await client.send(
                client.build_request("GET", url, headers=headers),
                stream=True,
                follow_redirects=False,
            )
            if upstream.status_code not in REDIRECT_STATUSES:
                break
            if redirect_count >= MAX_REDIRECTS:
                raise CoverImageError("too many cover redirects", status_code=502)
            location = upstream.headers.get("location")
            previous_url = str(upstream.url)
            await upstream.aclose()
            upstream = None
            if not location:
                raise CoverImageError("cover redirect has no location", status_code=502)
            next_url = urljoin(previous_url, location)
            headers = httpx.Headers(headers_for_redirect(dict(headers), url, next_url))
            url = next_url

        if upstream is None or upstream.status_code != 200:
            raise CoverImageError("cover upstream returned an error", status_code=502)
        declared_type = upstream.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        media_type = _MEDIA_ALIASES.get(declared_type, declared_type)
        if media_type not in _MEDIA_TYPES:
            raise CoverImageError("cover content type is not supported", status_code=502)
        declared_length = upstream.headers.get("content-length")
        if declared_length is not None:
            try:
                if int(declared_length) > MAX_IMAGE_BYTES:
                    raise CoverImageError("cover image is too large", status_code=502)
            except ValueError as exc:
                raise CoverImageError("invalid cover content length", status_code=502) from exc

        chunks: list[bytes] = []
        length = 0
        async for chunk in upstream.aiter_bytes():
            length += len(chunk)
            if length > MAX_IMAGE_BYTES:
                raise CoverImageError("cover image is too large", status_code=502)
            chunks.append(chunk)
        body = b"".join(chunks)
        if _detected_media_type(body) != media_type:
            raise CoverImageError("cover image signature is invalid", status_code=502)
        return body, media_type
    finally:
        if upstream is not None:
            await upstream.aclose()


def _parse_allowed_url(url: str) -> tuple[ParseResult, str]:
    if not url or len(url) > MAX_URL_LENGTH:
        raise CoverImageError("cover URL is empty or too long")
    if "\\" in url or "#" in url:
        raise CoverImageError("cover URL cannot contain a fragment")
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise CoverImageError("cover URL is malformed") from exc
    if parsed.username is not None or parsed.password is not None:
        raise CoverImageError("cover URL cannot contain credentials")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise CoverImageError("cover URL has no host")
    # Netease (and some other CDNs) still publish http:// cover URLs. Upgrade
    # those to https:// before any fetch so we never talk to port 80.
    scheme = parsed.scheme.lower()
    if scheme == "http" and port in {None, 80}:
        host_for_netloc = host if ":" not in host else f"[{host}]"
        parsed = parsed._replace(scheme="https", netloc=host_for_netloc)
        port = parsed.port
    if parsed.scheme.lower() != "https" or port not in {None, 443}:
        raise CoverImageError("cover URL must use HTTPS port 443")

    path = unquote(parsed.path)
    if "\\" in path or any(part in {".", ".."} for part in path.split("/")):
        raise CoverImageError("cover URL path is malformed")
    if host == "y.gtimg.cn":
        if path != "/music/photo_new" and not path.startswith("/music/photo_new/"):
            raise CoverImageError("QQ cover path is not allowed")
    elif host_matches(host, ("music.126.net",)):
        pass
    elif host in _BILIBILI_HOSTS:
        if path != "/bfs" and not path.startswith("/bfs/"):
            raise CoverImageError("Bilibili cover path is not allowed")
    else:
        raise CoverImageError("cover URL host is not allowed")
    return parsed, host


def _detected_media_type(body: bytes) -> str | None:
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    return None


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    return any(
        candidate in {"*", etag, f"W/{etag}"}
        for candidate in (item.strip() for item in header.split(","))
    )

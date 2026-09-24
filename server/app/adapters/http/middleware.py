from __future__ import annotations

import secrets
import uuid
from collections.abc import Awaitable, Callable
from urllib.parse import unquote

import structlog
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware, GZipResponder, IdentityResponder
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

# Starlette's own list only covers a few image types. Audio previews, covers,
# library files and downloads would otherwise be gzipped, which drops
# Content-Length and breaks Range. 206 responses are skipped by the base
# responder itself (`partial_response`), so they need no entry here.
GZIP_EXCLUDED_CONTENT_TYPES = (
    "text/event-stream",
    "audio/*",
    "video/*",
    "image/*",
    "application/octet-stream",
    "binary/octet-stream",
)


class ExcludingGZipMiddleware(GZipMiddleware):
    """Compress JSON API bodies; leave media streams and 206 ranges uncompressed."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if "gzip" in headers.get("Accept-Encoding", ""):
            responder: ASGIApp = GZipResponder(
                self.app,
                self.minimum_size,
                compresslevel=self.compresslevel,
                thread_minimum_size=self.thread_minimum_size,
                exclude_content_types=GZIP_EXCLUDED_CONTENT_TYPES,
            )
        else:
            responder = IdentityResponder(
                self.app,
                self.minimum_size,
                exclude_content_types=GZIP_EXCLUDED_CONTENT_TYPES,
            )
        await responder(scope, receive, send)


# Reads the open dashboard needs: charts, catalog, search, in-page previews,
# lyrics and the health probe.  Everything else under /api/v1 — the library list, the
# downloaded files themselves, the download history and every write — needs the
# token as soon as API_TOKEN is set.
PUBLIC_READ_PREFIXES = (
    "/api/v1/platforms",
    "/api/v1/boards",
    "/api/v1/catalog",
    "/api/v1/search",
    "/api/v1/health",
    "/api/v1/cover-image",
    "/api/v1/preview",
    "/api/v1/lyrics",
)
# The browser keeps the same token locally and mirrors it into a cookie, because
# <audio src> / <a href> media URLs cannot carry a request header.
TOKEN_COOKIE_NAME = "musico_api_token"


def _matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)


def _request_token_matches(
    request: Request, expected: str, *, allow_cookie: bool = False
) -> bool:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
        if provided and secrets.compare_digest(provided, expected):
            return True
    provided = request.headers.get("x-api-token", "")
    if provided and secrets.compare_digest(provided, expected):
        return True
    if allow_cookie:
        cookie = unquote(request.cookies.get(TOKEN_COOKIE_NAME, ""))
        if cookie and secrets.compare_digest(cookie, expected):
            return True
    return False


class ApiTokenMiddleware(BaseHTTPMiddleware):
    """Token gate for everything under /api/v1 that is not a public read.

    Charts, catalog, search, previews and health stay open, so the dashboard
    keeps working behind a reverse proxy that authenticates on its own.  The
    library and the download history do not: they hand out the downloaded
    files themselves, so they need the token once API_TOKEN is set — for reads
    as well as for writes.

    A browser sends that token twice: as ``X-API-Token`` on the fetches it
    makes, and as a same-site cookie for the media URLs it cannot attach a
    header to.  The cookie is only honoured for GET / HEAD, so a cross-site
    request can never turn into a write.
    """

    def __init__(self, app: ASGIApp, api_token: str) -> None:
        super().__init__(app)
        self._api_token = api_token

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self._api_token or not request.url.path.startswith("/api/v1/"):
            return await call_next(request)
        method = request.method.upper()
        if method == "OPTIONS" or (
            method in {"GET", "HEAD"}
            and _matches_prefix(request.url.path, PUBLIC_READ_PREFIXES)
        ):
            return await call_next(request)
        if not _request_token_matches(
            request, self._api_token, allow_cookie=method in {"GET", "HEAD"}
        ):
            return JSONResponse(
                status_code=401,
                content={
                    "code": 40101,
                    "data": None,
                    "msg": "unauthorized: missing or invalid API token",
                },
            )
        return await call_next(request)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

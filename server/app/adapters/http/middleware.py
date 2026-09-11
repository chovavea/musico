from __future__ import annotations

import secrets
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


def _request_token_matches(request: Request, expected: str) -> bool:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
        if provided and secrets.compare_digest(provided, expected):
            return True
    provided = request.headers.get("x-api-token", "")
    return bool(provided) and secrets.compare_digest(provided, expected)


class ApiTokenMiddleware(BaseHTTPMiddleware):
    """Optional token gate for state-changing /api/v1 requests.

    Read endpoints stay open so the dashboard works behind a reverse proxy;
    set API_TOKEN to require a token for POST / PUT / DELETE / PATCH calls.
    """

    def __init__(self, app: ASGIApp, api_token: str) -> None:
        super().__init__(app)
        self._api_token = api_token

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if (
            self._api_token
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.url.path.startswith("/api/v1/")
            and not _request_token_matches(request, self._api_token)
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

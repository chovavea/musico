from __future__ import annotations

from app.adapters.http.middleware import (
    TOKEN_COOKIE_NAME,
    ApiTokenMiddleware,
    _request_token_matches,
)
from fastapi import FastAPI
from starlette.requests import Request
from starlette.testclient import TestClient


def _request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/downloads",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1),
        "scheme": "http",
    }
    return Request(scope)


def test_missing_token_rejected() -> None:
    assert not _request_token_matches(_request({}), "secret")


def test_bearer_token_accepted() -> None:
    assert _request_token_matches(_request({"authorization": "Bearer secret"}), "secret")


def test_bearer_prefix_mismatch_rejected() -> None:
    assert not _request_token_matches(_request({"authorization": "Bearer wrong"}), "secret")


def test_x_api_token_header_accepted() -> None:
    assert _request_token_matches(_request({"x-api-token": "secret"}), "secret")


def test_empty_configured_token_disabled() -> None:
    # No configured token means the gate is off; helper returns False but the
    # middleware only runs when api_token is non-empty.
    assert not _request_token_matches(_request({"authorization": "Bearer x"}), "")


def test_cookie_ignored_unless_explicitly_allowed() -> None:
    request = _request({"cookie": f"{TOKEN_COOKIE_NAME}=secret"})

    assert not _request_token_matches(request, "secret")
    assert _request_token_matches(request, "secret", allow_cookie=True)


def _guarded_client(api_token: str) -> TestClient:
    app = FastAPI()
    app.add_middleware(ApiTokenMiddleware, api_token=api_token)

    @app.get("/api/v1/boards")
    async def boards() -> dict[str, str]:
        return {"route": "boards"}

    @app.get("/api/v1/library")
    async def library() -> dict[str, str]:
        return {"route": "library"}

    @app.get("/api/v1/library/{asset_id}/stream")
    async def library_stream(asset_id: str) -> dict[str, str]:
        return {"route": asset_id}

    @app.post("/api/v1/downloads")
    async def create_download() -> dict[str, str]:
        return {"route": "create"}

    return TestClient(app)


def test_public_reads_need_no_token() -> None:
    client = _guarded_client("secret")

    response = client.get("/api/v1/boards")

    assert response.status_code == 200


def test_library_reads_require_the_token() -> None:
    client = _guarded_client("secret")

    anonymous = client.get("/api/v1/library")

    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == 40101
    assert client.get(
        "/api/v1/library", headers={"x-api-token": "secret"}
    ).status_code == 200
    assert client.get(
        "/api/v1/library", headers={"authorization": "Bearer secret"}
    ).status_code == 200


def test_media_urls_authenticate_with_the_cookie() -> None:
    """<audio src> / <a href> cannot send a header, so the cookie must work."""
    client = _guarded_client("secret token")
    client.cookies.set(TOKEN_COOKIE_NAME, "secret%20token")

    response = client.get("/api/v1/library/asset-1/stream")

    assert response.status_code == 200
    assert response.json() == {"route": "asset-1"}


def test_the_cookie_cannot_authorize_a_write() -> None:
    client = _guarded_client("secret")
    client.cookies.set(TOKEN_COOKIE_NAME, "secret")

    with_cookie = client.post("/api/v1/downloads")

    assert with_cookie.status_code == 401
    assert client.post(
        "/api/v1/downloads", headers={"x-api-token": "secret"}
    ).status_code == 200


def test_reads_stay_open_when_no_token_is_configured() -> None:
    client = _guarded_client("")

    assert client.get("/api/v1/library").status_code == 200

from __future__ import annotations

from app.adapters.http.middleware import _request_token_matches
from starlette.requests import Request


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

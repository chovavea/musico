from __future__ import annotations

from typing import Any

from app.adapters.http.routes import build_router
from fastapi import FastAPI
from starlette.testclient import TestClient


class _RecordingService:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    async def tasks(self, limit: int, offset: int) -> list[dict[str, Any]]:
        self.calls.append((limit, offset))
        return []


def _client(service: _RecordingService) -> TestClient:
    app = FastAPI()
    app.include_router(build_router())
    app.state.download_service = service
    return TestClient(app)


def test_download_history_defaults_to_the_newest_hundred() -> None:
    service = _RecordingService()

    with _client(service) as client:
        response = client.get("/api/v1/downloads")

    assert response.status_code == 200
    assert response.json()["data"] == {"items": []}
    assert service.calls == [(100, 0)]


def test_download_history_accepts_paging_parameters() -> None:
    service = _RecordingService()

    with _client(service) as client:
        response = client.get("/api/v1/downloads?limit=25&offset=50")

    assert response.status_code == 200
    assert service.calls == [(25, 50)]


def test_download_history_rejects_an_absurd_page_size() -> None:
    service = _RecordingService()

    with _client(service) as client:
        response = client.get("/api/v1/downloads?limit=100000")

    assert response.status_code == 422
    assert service.calls == []

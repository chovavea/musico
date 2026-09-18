from __future__ import annotations

from pathlib import Path
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


class _Asset:
    format = "flac"


class _Track:
    title = "夜曲"
    artist = "周杰伦"


class _AssetService:
    """Stand-in for DownloadService.asset() that resolves one library file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def asset(self, asset_id: str) -> tuple[Any, Path, Any] | None:
        if asset_id != "asset-1":
            return None
        return _Asset(), self._path, _Track()


def _client(service: Any) -> TestClient:
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


def test_library_stream_is_inline_while_download_is_an_attachment(tmp_path: Path) -> None:
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"fLaC" + b"\x00" * 64)
    service = _AssetService(audio)

    with _client(service) as client:
        stream = client.get("/api/v1/library/asset-1/stream")
        download = client.get("/api/v1/library/asset-1/download")

    assert stream.status_code == 200
    assert download.status_code == 200
    # <audio src> plays the stream URL in place; the download route saves it.
    assert stream.headers["content-disposition"].startswith("inline;")
    assert download.headers["content-disposition"].startswith("attachment;")

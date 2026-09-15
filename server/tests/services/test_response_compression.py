from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.adapters.http.middleware import ExcludingGZipMiddleware
from app.main import create_app
from app.settings import Settings
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
from starlette.testclient import TestClient

BOARDS_YAML = Path(__file__).resolve().parents[3] / "configs" / "boards.yaml"

_CHUNK = b"\xff\xfb" + b"a" * 4096


class _FakeSearchService:
    """Stands in for the real service so this test needs no database."""

    async def search(
        self,
        query: str,
        *,
        kind: str = "full",
        limit: int | None = None,
    ) -> dict[str, Any]:
        items = [
            {
                "platform": "qqmusic",
                "external_id": f"mid-{index}",
                "title": f"搜索测试歌曲 {index}",
                "artist": "测试歌手",
                "platforms": [],
                "platform_count": 1,
            }
            for index in range(200)
        ]
        return {"query": query, "type": kind, "items": items, "platforms": [], "partial": False}


def _app() -> FastAPI:
    settings = Settings(boards_yaml=BOARDS_YAML, enable_media_resolver=False)
    app = create_app(settings, start_scheduler=False, run_migrations=False)
    app.state.search_service = _FakeSearchService()
    return app


def _client() -> TestClient:
    return TestClient(_app())


def _media_app() -> FastAPI:
    """SPA static files would swallow routes added after create_app."""
    app = FastAPI()
    app.add_middleware(ExcludingGZipMiddleware, minimum_size=1024)

    @app.get("/audio-stream")
    async def audio_stream() -> StreamingResponse:
        async def chunks() -> AsyncIterator[bytes]:
            yield _CHUNK
            yield _CHUNK

        return StreamingResponse(chunks(), media_type="audio/mpeg")

    @app.get("/cover")
    async def cover() -> Response:
        return Response(_CHUNK * 2, media_type="image/jpeg")

    @app.get("/download")
    async def download() -> Response:
        return Response(_CHUNK * 2, media_type="application/octet-stream")

    @app.get("/partial")
    async def partial() -> Response:
        return Response(
            _CHUNK,
            status_code=206,
            media_type="application/json",
            headers={"content-range": "bytes 0-4097/8000"},
        )

    return app


def test_search_json_is_gzipped_when_the_client_accepts_it() -> None:
    response = _client().get(
        "/api/v1/search?q=x&limit=100",
        headers={"accept-encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["vary"].lower() == "accept-encoding"
    assert len(response.json()["data"]["items"]) == 200
    # The test client decodes the body, so the wire size can only come from the
    # payload itself: the same JSON is ~4x larger than its gzip form.
    assert len(response.content) > 20_000


def test_search_json_stays_plain_when_the_client_refuses_gzip() -> None:
    response = _client().get(
        "/api/v1/search?q=x&limit=100",
        headers={"accept-encoding": "identity"},
    )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert len(response.json()["data"]["items"]) == 200


def test_small_json_responses_are_left_alone() -> None:
    """/api/v1/platforms is a few hundred bytes; compressing it is pure overhead."""
    response = _client().get("/api/v1/platforms", headers={"accept-encoding": "gzip"})

    assert response.status_code == 200
    assert "content-encoding" not in response.headers


def test_the_gzip_layer_keeps_audio_covers_downloads_and_ranges_uncompressed() -> None:
    """Starlette 1.4 does not exclude media types; the wrapper must skip them."""
    entries = [item for item in _app().user_middleware if item.cls is ExcludingGZipMiddleware]
    assert len(entries) == 1
    assert entries[0].kwargs["minimum_size"] == 1024

    client = TestClient(_media_app())
    headers = {"accept-encoding": "gzip"}
    audio = client.get("/audio-stream", headers=headers)
    cover = client.get("/cover", headers=headers)
    download = client.get("/download", headers=headers)
    partial = client.get("/partial", headers=headers)

    assert audio.status_code == 200
    assert cover.status_code == 200
    assert download.status_code == 200
    assert partial.status_code == 206
    assert "content-encoding" not in audio.headers
    assert "content-encoding" not in cover.headers
    assert "content-encoding" not in download.headers
    assert "content-encoding" not in partial.headers
    assert audio.content.startswith(b"\xff\xfb")
    assert partial.headers["content-range"] == "bytes 0-4097/8000"

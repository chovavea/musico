from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from app.adapters.http.routes import build_router
from app.domain.models import (
    AudioQuality,
    DownloadCandidate,
    DownloadResponse,
    PreviewInfo,
    TrackRef,
)
from app.download_sources.registry import DownloadSourceRecord, DownloadSourceRegistry
from app.plugins._registry import PluginRecord, PluginRegistry
from fastapi import FastAPI

TRACK = TrackRef(
    platform="netease", external_id="123", title="晴天", artist="周杰伦", duration_ms=269_000
)
OFFICIAL_URL = "https://music.163.com/official.mp3"
ENDPOINT = "/api/v1/preview/netease/123/stream"
PARAMS = TRACK.model_dump(exclude={"platform", "external_id"}, exclude_none=True)


class Official:
    def __init__(self, url: str | None = None, *, fails: bool = False) -> None:
        self.url = url
        self.fails = fails
        self.calls = 0

    async def preview(self, _track: TrackRef) -> PreviewInfo:
        self.calls += 1
        if self.fails:
            raise httpx.ReadTimeout("upstream unavailable")
        return PreviewInfo(preview_url=self.url)


class Source:
    def __init__(
        self, source_id: str, *, search_fails: bool = False, resolve_fails: bool = False
    ) -> None:
        self.source_id = source_id
        self.candidates = [candidate(source_id)]
        self.searched: list[TrackRef] = []
        self.resolved: list[str] = []
        self.search_fails = search_fails
        self.resolve_fails = resolve_fails
        self.headers: dict[str, str] = {}

    async def search(self, track: TrackRef) -> list[DownloadCandidate]:
        self.searched.append(track)
        if self.search_fails:
            raise ValueError("search unavailable")
        return self.candidates

    async def resolve(self, item: DownloadCandidate, *, offset: int = 0) -> DownloadResponse:
        self.resolved.append(item.source_track_id)
        if self.resolve_fails:
            raise ValueError("resolve unavailable")
        return DownloadResponse(
            url=f"https://{self.source_id}.example/{item.source_track_id}.flac",
            headers=self.headers,
        )


def candidate(source_id: str, **changes: object) -> DownloadCandidate:
    values = {
        "source_id": source_id,
        "source_track_id": "song",
        "title": TRACK.title,
        "artist": TRACK.artist,
        "duration_ms": TRACK.duration_ms,
        "quality": AudioQuality(format="flac", sample_rate_hz=44_100, bit_depth=16),
    }
    return DownloadCandidate.model_validate(values | changes)


def record(source: Source, *, priority: int = 0) -> DownloadSourceRecord:
    return DownloadSourceRecord(
        source_id=source.source_id,
        name=source.source_id,
        priority=priority,
        hosts=(f"{source.source_id}.example",),
        config_schema={},
        source=source,
    )


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolver(_host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr("app.adapters.http.safety._default_resolver", resolver)


@asynccontextmanager
async def client_for(
    official: Official | None,
    sources: list[DownloadSourceRecord],
    handler: Callable[[httpx.Request], httpx.Response],
    settings: object | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = FastAPI()
        app.include_router(build_router())
        app.state.preview_client = upstream
        app.state.registry = PluginRegistry(
            plugins={
                "netease": PluginRecord(
                    plugin_id="netease",
                    name="网易云",
                    capabilities=[],
                    config_schema={},
                    preview=official,
                )
            }
        )
        app.state.download_sources = DownloadSourceRegistry(
            sources={source.source_id: source for source in sources}
        )
        if settings is not None:
            app.state.settings = settings
        # No database, download service or worker: listening must not enqueue a download.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


def audio(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"fLaC-audio", headers={"Content-Type": "audio/flac"})


async def test_official_audio_still_takes_precedence() -> None:
    source = Source("backup")
    official = Official(OFFICIAL_URL)
    async with client_for(official, [record(source)], audio) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert response.content == b"fLaC-audio"
    assert official.calls == 1
    assert not source.searched


@pytest.mark.parametrize("official", [None, Official(), Official(fails=True)])
async def test_highest_priority_site_is_used_without_asking_the_rest(
    official: Official | None,
) -> None:
    lower, higher = Source("lower"), Source("higher")
    async with client_for(official, [record(lower), record(higher, priority=10)], audio) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert higher.searched == [TRACK]
    assert higher.resolved == ["song"]
    assert lower.searched == []


async def test_download_sources_are_searched_one_at_a_time() -> None:
    order: list[str] = []
    in_flight = 0
    peak = 0

    class Tracked(Source):
        async def search(self, track: TrackRef) -> list[DownloadCandidate]:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            order.append(self.source_id)
            await asyncio.sleep(0)
            in_flight -= 1
            return await super().search(track)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if request.url.host == "first.example" else audio(request)

    first, second, third = Tracked("first"), Tracked("second"), Tracked("third")
    async with client_for(
        Official(), [record(source) for source in (first, second, third)], handler
    ) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    # The third site is never contacted once the second one plays.
    assert order == ["first", "second"]
    assert peak == 1
    assert third.searched == []


async def test_priority_decides_which_site_is_asked_first() -> None:
    broken, backup = Source("broken", search_fails=True), Source("backup")
    async with client_for(
        Official(), [record(backup, priority=5), record(broken, priority=9)], audio
    ) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert broken.searched == [TRACK]
    assert backup.resolved == ["song"]


@pytest.mark.parametrize(
    ("status", "content_type", "body"),
    [
        (404, "audio/mpeg", b"missing"),
        (403, "audio/mpeg", b"forbidden"),
        (500, "audio/mpeg", b"error"),
        (200, "Text/HTML; charset=utf-8", b"<html>login</html>"),
        (200, "application/json", b'{"error": "missing"}'),
        (200, "audio/mpeg", b"<html>not audio</html>"),
        (200, "audio/mpeg", b""),
        (204, "audio/mpeg", b""),
        (302, "audio/mpeg", b""),
    ],
)
async def test_unavailable_official_stream_falls_back(
    status: int, content_type: str, body: bytes
) -> None:
    source = Source("backup")
    closed: list[httpx.Response] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "music.163.com":
            response = httpx.Response(status, content=body, headers={"Content-Type": content_type})
            closed.append(response)
            return response
        return audio(request)

    async with client_for(Official(OFFICIAL_URL), [record(source)], handler) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert response.content == b"fLaC-audio"
    assert all(item.is_closed for item in closed)
    assert source.resolved == ["song"]


async def test_download_only_skips_an_already_failed_official_player() -> None:
    official, source = Official(OFFICIAL_URL), Source("backup")
    async with client_for(official, [record(source)], audio) as client:
        response = await client.get(ENDPOINT, params=PARAMS | {"download_only": "true"})
    assert response.status_code == 200
    assert official.calls == 0
    assert source.resolved == ["song"]


async def test_one_failed_site_does_not_prevent_later_sites() -> None:
    failed_search = Source("a", search_fails=True)
    failed_resolve = Source("b", resolve_fails=True)
    unavailable, good = Source("c"), Source("d")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if request.url.host == "c.example" else audio(request)

    sources = [failed_search, failed_resolve, unavailable, good]
    async with client_for(Official(), [record(source) for source in sources], handler) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert all(source.searched == [TRACK] for source in sources)
    assert failed_resolve.resolved == ["song"]
    assert unavailable.resolved == ["song"]
    assert good.resolved == ["song"]


async def test_a_hanging_source_is_bounded_by_the_call_timeout_and_skipped() -> None:
    cancelled = asyncio.Event()

    class SlowSource(Source):
        async def search(self, track: TrackRef) -> list[DownloadCandidate]:
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()
            return []

    settings = SimpleNamespace(preview_call_timeout_sec=0.02)
    slow, good = SlowSource("slow"), Source("good")
    # The hanging site is asked first, so its timeout must not block the next one.
    async with client_for(
        Official(), [record(slow, priority=5), record(good)], audio, settings=settings
    ) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert cancelled.is_set()
    assert good.resolved == ["song"]


async def test_candidates_must_match_track_and_be_browser_playable() -> None:
    source = Source("backup")
    source.candidates = [
        candidate("backup", title="另一首歌"),
        candidate("backup", artist="另一位歌手"),
        candidate("backup", duration_ms=100_000),
        candidate("another"),
        candidate("backup", quality=AudioQuality(format="dsf")),
        candidate("backup", source_track_id="correct"),
    ]
    async with client_for(Official(), [record(source)], audio) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert source.resolved == ["correct"]


async def test_listening_prefers_smaller_audio_but_retries_other_qualities() -> None:
    source = Source("backup")
    source.candidates = [
        candidate(
            "backup",
            source_track_id="hires",
            quality=AudioQuality(format="flac", sample_rate_hz=192_000, bit_depth=24),
        ),
        candidate("backup", source_track_id="cd"),
        candidate("backup", source_track_id="mp3", quality=AudioQuality(format="mp3")),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return audio(request) if request.url.path == "/hires.flac" else httpx.Response(404)

    async with client_for(Official(), [record(source)], handler) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert source.resolved == ["mp3", "cd", "hires"]


async def test_no_match_or_no_metadata_returns_404_without_a_download() -> None:
    source = Source("backup")
    source.candidates = [candidate("backup", artist="另一位歌手")]
    async with client_for(Official(), [record(source)], audio) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
        legacy = await client.get(ENDPOINT)
    assert response.status_code == legacy.status_code == 404
    assert source.searched == [TRACK]
    assert not source.resolved


async def test_legacy_official_stream_url_still_works() -> None:
    async with client_for(Official(OFFICIAL_URL), [], audio) as client:
        response = await client.get(ENDPOINT)
    assert response.status_code == 200


async def test_range_and_headers_are_preserved_without_forwarding_client_credentials() -> None:
    source = Source("backup")
    source.headers = {"Referer": "https://backup.example/", "Range": "bytes=999-"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["range"] == "bytes=8-11"
        assert request.headers["referer"] == "https://backup.example/"
        assert request.headers["accept-encoding"] == "identity"
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        return httpx.Response(
            206,
            content=b"part",
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Range": "bytes 8-11/100",
                "Accept-Ranges": "bytes",
                "Content-Disposition": "attachment; filename=song.flac",
            },
        )

    async with client_for(Official(), [record(source)], handler) as client:
        response = await client.get(
            ENDPOINT,
            params=PARAMS,
            headers={"Range": "bytes=8-11", "Authorization": "CHANGE_ME", "Cookie": "CHANGE_ME"},
        )
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 8-11/100"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "audio/flac"
    assert response.headers["content-length"] == "4"
    assert "content-disposition" not in response.headers
    assert response.content == b"part"


async def test_partial_audio_bytes_are_not_mistaken_for_a_text_error() -> None:
    source = Source("backup")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            206,
            content=b"<\x00\x01\x02",
            headers={"Content-Type": "audio/flac", "Content-Range": "bytes 8-11/100"},
        )

    async with client_for(Official(), [record(source)], handler) as client:
        response = await client.get(ENDPOINT, params=PARAMS, headers={"Range": "bytes=8-11"})
    assert response.status_code == 206
    assert response.content == b"<\x00\x01\x02"


@pytest.mark.parametrize("destination", ["https://evil.example/song", "http://127.0.0.1/song"])
async def test_each_redirect_is_guarded_before_requesting_it(destination: str) -> None:
    rejected, good = Source("first"), Source("second")
    first = record(rejected)
    first.hosts += ("127.0.0.1",)
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host)
        if request.url.host == "first.example":
            return httpx.Response(302, headers={"Location": destination})
        return audio(request)

    async with client_for(Official(), [first, record(good)], handler) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert requests == ["first.example", "second.example"]


async def test_cross_origin_redirect_drops_sensitive_source_headers() -> None:
    source = Source("backup")
    source.headers = {
        "Authorization": "CHANGE_ME",
        "X-Api-Key": "CHANGE_ME",
        "Cookie": "CHANGE_ME",
        "Referer": "https://backup.example/",
    }
    source_record = record(source)
    source_record.hosts += ("cdn.example",)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "backup.example":
            assert request.headers["authorization"] == "CHANGE_ME"
            return httpx.Response(307, headers={"Location": "https://cdn.example/audio.flac"})
        assert request.url.host == "cdn.example"
        assert "authorization" not in request.headers
        assert "x-api-key" not in request.headers
        assert "cookie" not in request.headers
        assert request.headers["range"] == "bytes=0-"
        assert request.headers["referer"] == "https://backup.example/"
        return audio(request)

    async with client_for(Official(), [source_record], handler) as client:
        response = await client.get(ENDPOINT, params=PARAMS, headers={"Range": "bytes=0-"})
    assert response.status_code == 200


async def test_source_without_host_allowlist_is_not_used() -> None:
    source = Source("backup")
    source_record = record(source)
    source_record.hosts = ()
    async with client_for(Official(), [source_record], audio) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 404
    assert not source.searched


async def test_failure_before_first_audio_bytes_closes_stream_and_falls_back() -> None:
    class BrokenStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            raise httpx.ReadError("audio unavailable")
            yield b""  # pragma: no cover

        async def aclose(self) -> None:
            self.closed = True

    broken = BrokenStream()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "music.163.com":
            return httpx.Response(200, stream=broken, headers={"Content-Type": "audio/mpeg"})
        return audio(request)

    source = Source("backup")
    async with client_for(Official(OFFICIAL_URL), [record(source)], handler) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert broken.closed
    assert source.resolved == ["song"]


async def test_invalid_metadata_is_rejected_without_searching() -> None:
    source = Source("backup")
    async with client_for(Official(), [record(source)], audio) as client:
        response = await client.get(ENDPOINT, params=PARAMS | {"duration_ms": -1})
    assert response.status_code == 422
    assert not source.searched

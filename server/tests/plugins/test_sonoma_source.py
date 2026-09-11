from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
from app.domain.models import DownloadCandidate, TrackRef
from app.download_sources.registry import load_download_sources
from app.download_sources.source_sonoma.source import SonomaSource


async def _offline_guard(_url: str, _hosts: object) -> None:
    """Every request is served by MockTransport, so skip the real DNS guard."""
    return None


@pytest.mark.asyncio
async def test_sonoma_search_parses_candidates_and_uses_form_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/ajax.php"
        assert request.url.params["act"] == "search"
        assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
        assert request.headers["cookie"] == "sl-session=fake"
        assert parse_qs(request.content.decode()) == {
            "keyword": ["晴天 周杰伦"],
            "page": ["1"],
            "size": ["30"],
        }
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {
                            "id": "sky",
                            "name": "晴天",
                            "artist": "周杰伦",
                            "album_name": "叶惠美",
                            "duration": "269",
                            "time": "269",
                            "sign": "signed",
                        }
                    ]
                },
            },
        )

    monkeypatch.setenv("MUSICO_DL_TEST_COOKIE", "sl-session=fake")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mirror.example",
    )
    try:
        source = SonomaSource(
            client,
            {
                "base_url": "https://mirror.example",
                "cookie_env": "MUSICO_DL_TEST_COOKIE",
                "max_results": 4,
            },
            url_guard=_offline_guard,
        )
        candidates = await source.search(
            TrackRef(
                platform="qqmusic",
                external_id="qq-1",
                title="晴天",
                artist="周杰伦",
                duration_ms=269_000,
                isrc="TWK970300101",
                version="live",
            )
        )
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.source_id == "sonoma"
        assert candidate.source_track_id == "sky:flac:2000"
        assert candidate.quality.format == "flac"
        assert candidate.duration_ms == 269_000
        assert candidate.isrc is None
        assert candidate.version is None
        assert candidate.locator == {
            "songid": "sky",
            "format": "flac",
            "bitrate": "2000",
            "time": "269",
            "sign": "signed",
            "match_score": 0.98,
        }
        assert [item.quality.format for item in candidates] == ["flac"]
        assert [item.locator["bitrate"] for item in candidates] == ["2000"]
        assert len(requests) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_sonoma_resolve_posts_locator_and_returns_range_header() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["act"] == "getUrl"
        assert parse_qs(request.content.decode()) == {
            "songid": ["sky"],
            "format": ["flac"],
            "time": ["269"],
            "bitrate": ["2000"],
            "sign": ["signed"],
        }
        return httpx.Response(
            200,
            json={"code": 0, "data": {"url": "https://m801.music.126.net/sky.flac"}},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mirror.example",
    )
    try:
        source = SonomaSource(
            client,
            {"base_url": "https://mirror.example"},
            url_guard=_offline_guard,
        )
        candidate = DownloadCandidate(
            source_id="sonoma",
            source_track_id="sky:flac:2000",
            title="晴天",
            artist="周杰伦",
            quality={"format": "flac"},
            locator={
                "songid": "sky",
                "format": "flac",
                "bitrate": "2000",
                "time": "269",
                "sign": "signed",
            },
        )
        resolved = await source.resolve(candidate, offset=10)
        assert resolved.url == "https://m801.music.126.net/sky.flac"
        assert resolved.headers == {
            "Referer": "https://mirror.example/",
            "Range": "bytes=10-",
        }
        assert len(requests) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_sonoma_does_not_resolve_non_flac_format() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mirror.example",
    )
    try:
        source = SonomaSource(
            client,
            {"base_url": "https://mirror.example"},
            url_guard=_offline_guard,
        )
        candidate = DownloadCandidate(
            source_id="sonoma",
            source_track_id="sky:mp3:320",
            title="晴天",
            artist="周杰伦",
            quality={"format": "flac"},
            locator={"songid": "sky", "format": "mp3", "bitrate": "320"},
        )
        with pytest.raises(ValueError, match="only supports FLAC"):
            await source.resolve(candidate)
        assert requests == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_sonoma_search_ignores_title_mismatches_even_when_query_has_isrc() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {
                            "id": "wrong",
                            "name": "七里香",
                            "artist": "周杰伦",
                            "duration": "269",
                            "time": "1710000000",
                            "sign": "other",
                        },
                        {
                            "id": "sky",
                            "name": "晴天",
                            "artist": "周杰伦",
                            "duration": "269",
                            "time": "1710000000",
                            "sign": "signed",
                        },
                    ]
                },
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mirror.example",
    )
    try:
        source = SonomaSource(
            client,
            {"base_url": "https://mirror.example"},
            url_guard=_offline_guard,
        )
        candidates = await source.search(
            TrackRef(
                platform="qqmusic",
                external_id="qq-1",
                title="晴天",
                artist="周杰伦",
                duration_ms=269_000,
                isrc="TWK970300101",
            )
        )
        assert [item.source_track_id for item in candidates] == ["sky:flac:2000"]
        assert candidates[0].isrc is None
        assert candidates[0].locator["time"] == "1710000000"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_sonoma_search_does_not_treat_signing_time_as_duration() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {
                            "id": "sky",
                            "name": "晴天",
                            "artist": "周杰伦",
                            "time": "1710000000",
                            "sign": "signed",
                        }
                    ]
                },
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mirror.example",
    )
    try:
        source = SonomaSource(
            client,
            {"base_url": "https://mirror.example"},
            url_guard=_offline_guard,
        )
        candidates = await source.search(
            TrackRef(
                platform="qqmusic",
                external_id="qq-1",
                title="晴天",
                artist="周杰伦",
                duration_ms=269_000,
            )
        )
        assert len(candidates) == 1
        assert candidates[0].duration_ms == 269_000
        assert candidates[0].locator["time"] == "1710000000"
        assert candidates[0].locator["match_score"] == 0.9
    finally:
        await client.aclose()


def test_sonoma_duration_ignores_signing_time() -> None:
    from app.download_sources.source_sonoma.source import _duration_ms

    assert _duration_ms({"time": "1710000000", "sign": "signed"}) is None
    assert _duration_ms({"duration": "269", "time": "1710000000"}) == 269_000
    assert _duration_ms({"interval": "4:29"}) == 269_000


@pytest.mark.asyncio
async def test_sonoma_search_treats_http_468_as_empty_result() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(468, text="challenge")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mirror.example",
    )
    try:
        source = SonomaSource(
            client,
            {"base_url": "https://mirror.example"},
            url_guard=_offline_guard,
        )
        assert await source.search(
            TrackRef(platform="qqmusic", external_id="1", title="晴天", artist="周杰伦")
        ) == []
    finally:
        await client.aclose()


def test_sonoma_source_registers_and_can_be_disabled() -> None:
    client = httpx.AsyncClient()
    try:
        registry = load_download_sources(
            client,
            config={
                "sources": [
                    {
                        "id": "sonoma",
                        "config": {"base_url": "https://mirror.example"},
                    }
                ]
            },
        )
        assert "sonoma" in registry.sources
        assert "music.126.net" in registry.sources["sonoma"].hosts
        assert "kuwo.cn" in registry.sources["sonoma"].hosts
        assert registry.sources["sonoma"].source._base_url == "https://mirror.example"

        disabled = load_download_sources(
            client,
            config={"sources": [{"id": "sonoma", "enabled": False}]},
        )
        assert "sonoma" not in disabled.sources
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_sonoma_source_rejects_invalid_cookie_env_name() -> None:
    client = httpx.AsyncClient()
    try:
        with pytest.raises(ValueError, match="cookie_env"):
            SonomaSource(
                client,
                {"base_url": "https://mirror.example", "cookie_env": "COOKIE-NAME"},
            )
    finally:
        import asyncio

        asyncio.run(client.aclose())

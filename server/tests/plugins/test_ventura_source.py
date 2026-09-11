import json

import httpx
import pytest
from app.domain.models import AudioQuality, DownloadCandidate, TrackRef
from app.download_sources.registry import load_download_sources
from app.download_sources.source_ventura.source import VenturaSource


async def _offline_guard(_url: str, _hosts: object) -> None:
    """Every request is served by MockTransport, so skip the real DNS guard."""
    return None


@pytest.mark.asyncio
async def test_ventura_source_posts_encoded_search_and_parses_quality_routes() -> None:
    requests: list[httpx.Request] = []
    result = {
        "id": "sky",
        "name": "晴天",
        "player": "周杰伦",
        "album": "叶惠美",
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            assert json.loads(request.content) == {
                "keyword": "%E6%99%B4%E5%A4%A9",
                "page": 1,
            }
            return httpx.Response(200, json={"status": True, "result": [result]})
        route = request.url.path.split("/")[2]
        detail = {
            "a": ("晴天", "周杰伦", "叶惠美", "iot202.music.126.net", "192000", "24"),
            "c": ("晴天", "周杰伦", "叶惠美", "m801.music.126.net", "96000", "24"),
            "b": ("晴天", "周杰伦", "叶惠美", "kw-er.kuwo.cn", "44100", "16"),
        }[route]
        title, artist, album, host, sample_rate, bit_depth = detail
        html = (
            '<script>self.__next_f.push([1,"{'
            f'\\"id\\":\\"sky\\",\\"url\\":\\"https://{host}/audio.flac?sig=abc\\",'
            f'\\"name\\":\\"{title}\\",\\"player\\":\\"{artist}\\",'
            f'\\"album\\":\\"{album}\\",\\"format\\":\\"flac\\",'
            f'\\"quality\\":\\"{bit_depth}bit {sample_rate}Hz\\"'
            '}"])])</script>'
        )
        return httpx.Response(200, text=html)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://mirror.example"
    )
    try:
        source = VenturaSource(
            client,
            {"base_url": "https://mirror.example", "max_results": 1},
            url_guard=_offline_guard,
        )
        candidates = await source.search(
            TrackRef(platform="qqmusic", external_id="1", title="晴天", artist="周杰伦")
        )
        assert len(candidates) == 3
        assert {item.quality.sample_rate_hz for item in candidates} == {
            44_100,
            96_000,
            192_000,
        }
        assert {item.quality.bit_depth for item in candidates} == {16, 24}
        assert all(item.title == "晴天" and item.artist == "周杰伦" for item in candidates)
        assert all("download_url" not in item.locator for item in candidates)
        post_requests = [request for request in requests if request.method == "POST"]
        assert len(post_requests) == 1
        assert all(
            request.headers["content-type"].startswith("application/json")
            for request in post_requests
        )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_ventura_source_reports_the_daily_quota_page_instead_of_crashing() -> None:
    limited = (
        "<div>今日访问已达限额，可明日再来。</div>"
        "<div>如果您已注册过，可登录后访问</div>"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "result": [{"id": "sky", "name": "晴天", "player": "周杰伦"}],
                },
            )
        return httpx.Response(200, text="".join(limited))

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mirror.example",
    )
    try:
        source = VenturaSource(
            client,
            {"base_url": "https://mirror.example", "max_results": 1},
            url_guard=_offline_guard,
        )
        track = TrackRef(platform="qqmusic", external_id="1", title="晴天", artist="周杰伦")
        assert await source.search(track) == []
        candidate = DownloadCandidate(
            source_id="ventura",
            source_track_id="https://mirror.example/music/a/sky",
            title="晴天",
            artist="周杰伦",
            quality=AudioQuality(format="flac"),
            locator={"detail_url": "https://mirror.example/music/a/sky"},
        )
        with pytest.raises(ValueError, match="no direct download link"):
            await source.resolve(candidate)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_ventura_source_uses_second_search_endpoint_only_as_fallback() -> None:
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            methods.append(request.url.path)
            if request.url.path.endswith("searchOnlineMusicTwo"):
                return httpx.Response(200, json={"status": True, "result": []})
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "result": [{"id": "sky", "name": "晴天", "player": "周杰伦"}],
                },
            )
        html = (
            '<script>self.__next_f.push([1,"{'
            '\\"url\\":\\"https://m801.music.126.net/audio.flac?sig=fake\\",'
            '\\"name\\":\\"晴天\\",\\"player\\":\\"周杰伦\\",\\"format\\":\\"flac\\"'
            '}"])])</script>'
        )
        return httpx.Response(200, text=html)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mirror.example",
    )
    try:
        source = VenturaSource(
            client,
            {"base_url": "https://mirror.example", "max_results": 1},
            url_guard=_offline_guard,
        )
        candidates = await source.search(
            TrackRef(platform="qqmusic", external_id="1", title="晴天", artist="周杰伦")
        )
        assert len(candidates) == 3
        assert methods == [
            "/api/player/searchOnlineMusicTwo",
            "/api/player/searchOnlineMusicOne",
        ]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_ventura_source_refreshes_signed_url_and_strips_rsc_escape() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        html = (
            '<script>self.__next_f.push([1,"{'
            '\\"id\\":\\"sky\\",\\"url\\":\\"https://m801.music.126.net/audio.flac?sig=fresh\\",'
            '\\"name\\":\\"晴天\\",\\"player\\":\\"周杰伦\\",\\"format\\":\\"flac\\"'
            '}"])])</script>'
        )
        return httpx.Response(200, text=html)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mirror.example",
    )
    try:
        source = VenturaSource(
            client,
            {"base_url": "https://mirror.example"},
            url_guard=_offline_guard,
        )
        candidate = {
            "source_id": "ventura",
            "source_track_id": "https://mirror.example/music/c/sky",
            "title": "晴天",
            "artist": "周杰伦",
            "quality": {"format": "flac", "sample_rate_hz": 96_000, "bit_depth": 24},
            "locator": {
                "detail_url": "https://mirror.example/music/c/sky",
                "download_url": "https://m801.music.126.net/audio.flac?sig=stale",
            },
        }
        from app.domain.models import DownloadCandidate

        resolved = await source.resolve(DownloadCandidate.model_validate(candidate), offset=10)
        assert calls == 1
        assert resolved.url == "https://m801.music.126.net/audio.flac?sig=fresh"
        assert resolved.headers["Range"] == "bytes=10-"
    finally:
        await client.aclose()


def test_ventura_quality_parser_does_not_guess_missing_dimensions() -> None:
    from app.download_sources.source_ventura.source import _quality_from_text

    unknown = _quality_from_text("无损音质")
    assert unknown.format == "flac"
    assert unknown.sample_rate_hz is None
    assert unknown.bit_depth is None

    precise = _quality_from_text("24bit 192000Hz")
    assert precise.format == "flac"
    assert precise.sample_rate_hz == 192_000
    assert precise.bit_depth == 24


def test_ventura_source_uses_explicit_page_quality_when_present() -> None:
    from app.download_sources.source_ventura.source import _extract_page_data

    html = (
        r'''<script>self.__next_f.push([1,"{\"url\":\"https://m801.music.126.net/'''
        r'''audio.flac\",\"format\":\"flac\",\"quality\":\"24bit 192000Hz\",'''
        r'''\"size\":\"52.8MB\"}"])</script>'''
    )
    page = _extract_page_data(
        html,
        "https://mirror.example/music/a/sky",
    )
    assert page.quality == "24bit 192000Hz"
    assert page.size_bytes == int(52.8 * 1024**2)


@pytest.mark.asyncio
async def test_ventura_source_uses_configured_base_url() -> None:
    requests: list[httpx.Request] = []

    async def allow(_url: str, hosts: object) -> None:
        assert "mirror.example" in hosts

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "result": [{"id": "sky", "name": "晴天", "player": "周杰伦"}],
                },
            )
        html = (
            '<script>self.__next_f.push([1,"{'
            '\\"url\\":\\"https://m801.music.126.net/audio.flac\\",'
            '\\"name\\":\\"晴天\\",\\"player\\":\\"周杰伦\\",\\"format\\":\\"flac\\"'
            '}"])])</script>'
        )
        return httpx.Response(200, text=html)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mirror.example",
    )
    try:
        source = VenturaSource(
            client,
            {"base_url": "https://mirror.example", "max_results": 1},
            url_guard=allow,
        )
        candidates = await source.search(
            TrackRef(platform="qqmusic", external_id="1", title="晴天", artist="周杰伦")
        )
        assert candidates
        assert all(str(request.url).startswith("https://mirror.example/") for request in requests)
        assert all(request.headers["referer"] == "https://mirror.example/" for request in requests)
        assert all(
            item.source_page_url.startswith("https://mirror.example/music/") for item in candidates
        )
    finally:
        await client.aclose()


def test_ventura_source_registers_configured_base_url_host() -> None:
    client = httpx.AsyncClient()
    try:
        registry = load_download_sources(
            client,
            config={
                "sources": [
                    {
                        "id": "ventura",
                        "hosts": ["cdn.mirror.example"],
                        "config": {"base_url": "https://mirror.example"},
                    }
                ]
            },
        )
        source = registry.sources["ventura"]
        assert "mirror.example" in source.hosts
        assert "cdn.mirror.example" in source.hosts
        assert source.source._base_url == "https://mirror.example"
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_ventura_source_rejects_invalid_base_url() -> None:
    client = httpx.AsyncClient()
    try:
        with pytest.raises(ValueError, match="base_url"):
            VenturaSource(client, {"base_url": "ftp://mirror.example"})
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_ventura_source_can_be_disabled() -> None:
    client = httpx.AsyncClient()
    try:
        registry = load_download_sources(
            client,
            config={"sources": [{"id": "ventura", "enabled": False}]},
        )
        assert "ventura" not in registry.sources
    finally:
        import asyncio

        asyncio.run(client.aclose())


@pytest.mark.asyncio
async def test_ventura_source_rejects_redirect_to_private_page() -> None:
    requests: list[str] = []

    async def guard(url: str, _hosts: object) -> None:
        if "127.0.0.1" in url:
            raise ValueError("outbound address is not public")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "result": [
                        {
                            "id": "sky",
                            "name": "晴天",
                            "player": "周杰伦",
                        }
                    ],
                },
            )
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mirror.example",
    )
    try:
        source = VenturaSource(
            client,
            {"base_url": "https://mirror.example"},
            url_guard=guard,
        )
        candidates = await source.search(
            TrackRef(platform="qqmusic", external_id="1", title="晴天", artist="周杰伦")
        )
        assert candidates == []
        assert all("127.0.0.1" not in url for url in requests)
    finally:
        await client.aclose()
def test_download_source_resolves_base_url_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MUSICO_DL_TEST_BASE_URL", "https://mirror.example")
    client = httpx.AsyncClient()
    try:
        registry = load_download_sources(
            client,
            config={
                "sources": [
                    {"id": "ventura", "config": {"base_url_env": "MUSICO_DL_TEST_BASE_URL"}}
                ]
            },
        )
        source = registry.sources["ventura"]
        assert source.source._base_url == "https://mirror.example"
        assert "mirror.example" in source.hosts
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_download_source_is_skipped_when_base_url_env_has_no_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MUSICO_DL_TEST_BASE_URL", raising=False)
    client = httpx.AsyncClient()
    try:
        registry = load_download_sources(
            client,
            config={
                "sources": [
                    {"id": "ventura", "config": {"base_url_env": "MUSICO_DL_TEST_BASE_URL"}}
                ]
            },
        )
        assert "ventura" not in registry.sources
    finally:
        import asyncio

        asyncio.run(client.aclose())

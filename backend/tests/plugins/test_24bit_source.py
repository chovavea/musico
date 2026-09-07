import httpx
import pytest

from app.download_sources.source_aries.source import AriesSource
from app.download_sources.registry import load_download_sources
from app.domain.models import TrackRef


@pytest.mark.asyncio
async def test_aries_source_parses_detail_and_direct_link() -> None:
    html = """
    <html><head><title>晴天 - 周杰伦</title></head>
    <body><a href="/download/sky.flac">24bit 96k FLAC</a></body></html>
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/search"):
            return httpx.Response(200, text='<a href="/music/sky">晴天</a>')
        return httpx.Response(200, text=html)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://www.example.invalid")
    try:
        source = AriesSource(client)
        candidates = await source.search(
            TrackRef(platform="qqmusic", external_id="1", title="晴天", artist="周杰伦")
        )
        assert len(candidates) == 1
        assert candidates[0].quality.format == "flac"
        resolved = await source.resolve(candidates[0])
        assert resolved.url.endswith("sky.flac")
    finally:
        await client.aclose()


def test_aries_source_can_be_disabled() -> None:
    client = httpx.AsyncClient()
    try:
        registry = load_download_sources(
            client,
            config={"sources": [{"id": "aries", "enabled": False}]},
        )
        assert "aries" not in registry.sources
    finally:
        import asyncio

        asyncio.run(client.aclose())

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.domain.models import BoardSpec
from app.plugins.netease.charts import NeteaseCharts
from app.plugins.qqmusic.charts import QQMusicCharts


class _FixtureTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self._payload)


class _RoutingTransport(httpx.AsyncBaseTransport):
    def __init__(self, toplist: dict[str, Any], detail: dict[str, Any]) -> None:
        self._toplist = toplist
        self._detail = detail

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if "musicu.fcg" in str(request.url):
            return httpx.Response(200, json=self._detail)
        return httpx.Response(200, json=self._toplist)


@pytest.mark.asyncio
async def test_qq_fixture_skips_bad_row(fixtures_dir: Path) -> None:
    payload = json.loads((fixtures_dir / "qq_toplist.json").read_text(encoding="utf-8"))
    client = httpx.AsyncClient(transport=_FixtureTransport(payload))
    charts = QQMusicCharts(client)
    spec = BoardSpec(
        id="qq_hot",
        platform="qqmusic",
        name="QQ",
        type="hot",
        interval_sec=1800,
        extra={"top_id": 26},
    )
    items = await charts.fetch_board(spec)
    assert [item.external_id for item in items] == ["0039MnYb0qxYhV", "000MkMni19LlJH"]
    assert items[0].title == "晴天"
    assert [item.rank for item in items] == [1, 3]
    await client.aclose()


@pytest.mark.asyncio
async def test_qq_uses_list_order_when_cur_count_is_index_score() -> None:
    payload = {
        "songlist": [
            {
                "cur_count": "143759",
                "data": {
                    "songmid": "000aaa",
                    "songname": "LEMONADE",
                    "singer": [{"name": "aespa"}],
                },
            },
            {
                "cur_count": "171721",
                "data": {
                    "songmid": "000bbb",
                    "songname": "天生刺猬",
                    "singer": [{"name": "张月"}],
                },
            },
        ]
    }
    client = httpx.AsyncClient(transport=_FixtureTransport(payload))
    charts = QQMusicCharts(client)
    spec = BoardSpec(
        id="qq_pop",
        platform="qqmusic",
        name="流行指数",
        type="catalog",
        interval_sec=1800,
        extra={"top_id": 4},
    )
    items = await charts.fetch_board(spec)
    assert [item.rank for item in items] == [1, 2]
    assert items[0].raw_score == 143759
    await client.aclose()


@pytest.mark.asyncio
async def test_qq_prefers_single_cover_from_detail_vs_slot() -> None:
    toplist = {
        "songlist": [
            {
                "cur_count": "1",
                "data": {
                    "songmid": "000aaa",
                    "songname": "新单曲",
                    "albummid": "001album",
                    "singer": [{"name": "歌手"}],
                },
            },
            {
                "cur_count": "2",
                "data": {
                    "songmid": "000bbb",
                    "songname": "老歌",
                    "albummid": "001album2",
                    "singer": [{"name": "老歌手"}],
                },
            },
        ]
    }
    detail = {
        "req": {
            "data": {
                "songInfoList": [
                    {"mid": "000aaa", "vs": ["", "000sing1e"]},
                    {"mid": "000bbb", "vs": []},
                ]
            }
        }
    }
    client = httpx.AsyncClient(transport=_RoutingTransport(toplist, detail))
    charts = QQMusicCharts(client)
    spec = BoardSpec(
        id="qq_hot",
        platform="qqmusic",
        name="QQ",
        type="hot",
        interval_sec=1800,
        extra={"top_id": 26},
    )
    items = await charts.fetch_board(spec)
    assert items[0].cover_url == "https://y.gtimg.cn/music/photo_new/T062R300x300M000000sing1e.jpg"
    assert items[1].cover_url == "https://y.gtimg.cn/music/photo_new/T002R300x300M000001album2.jpg"
    await client.aclose()


@pytest.mark.asyncio
async def test_netease_fixture_skips_bad_row(fixtures_dir: Path) -> None:
    payload = json.loads((fixtures_dir / "netease_playlist.json").read_text(encoding="utf-8"))
    client = httpx.AsyncClient(transport=_FixtureTransport(payload))
    charts = NeteaseCharts(client)
    spec = BoardSpec(
        id="netease_hot",
        platform="netease",
        name="Netease",
        type="hot",
        interval_sec=1800,
        extra={"playlist_id": "3778678"},
    )
    items = await charts.fetch_board(spec)
    assert [item.external_id for item in items] == ["186016", "186001"]
    await client.aclose()

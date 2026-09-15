from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.domain.models import BoardSpec
from app.plugins.bilibili.charts import BilibiliCharts
from app.plugins.kugou.charts import KugouCharts
from app.plugins.kuwo.charts import KuwoCharts, parse_catalog_page
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


class _BilibiliChartTransport(httpx.AsyncBaseTransport):
    def __init__(self, periods: dict[str, Any], music_list: dict[str, Any]) -> None:
        self._periods = periods
        self._music_list = music_list

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/all_period"):
            return httpx.Response(200, json=self._periods)
        if request.url.path.endswith("/music_list"):
            return httpx.Response(200, json=self._music_list)
        return httpx.Response(404)


class _KugouChartTransport(httpx.AsyncBaseTransport):
    def __init__(self, rank_list: dict[str, Any], rank_song: dict[str, Any]) -> None:
        self._rank_list = rank_list
        self._rank_song = rank_song

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rank/list"):
            return httpx.Response(200, json=self._rank_list)
        if request.url.path.endswith("/rank/song"):
            return httpx.Response(200, json=self._rank_song)
        return httpx.Response(404)


class _KugouPagedSongTransport(httpx.AsyncBaseTransport):
    def __init__(self, pages: dict[int, dict[str, Any]]) -> None:
        self._pages = pages
        self.requested: list[int] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        self.requested.append(page)
        payload = self._pages.get(page)
        if payload is None:
            return httpx.Response(200, json={"status": 1, "data": {"total": 0, "info": []}})
        return httpx.Response(200, json=payload)


class _KuwoBangTransport(httpx.AsyncBaseTransport):
    def __init__(self, pages: dict[int, dict[str, Any]]) -> None:
        self._pages = pages
        self.requested: list[int] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("pn", "0"))
        self.requested.append(page)
        payload = self._pages.get(page)
        if payload is None:
            return httpx.Response(200, json={"num": "0", "musiclist": []})
        return httpx.Response(200, json=payload)


class _KuwoCatalogTransport(httpx.AsyncBaseTransport):
    def __init__(self, html: str) -> None:
        self._html = html

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=self._html)


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


@pytest.mark.asyncio
async def test_bilibili_fixture_parses_music_toplist(fixtures_dir: Path) -> None:
    periods = json.loads((fixtures_dir / "bilibili_periods.json").read_text(encoding="utf-8"))
    music_list = json.loads((fixtures_dir / "bilibili_music_list.json").read_text(encoding="utf-8"))
    client = httpx.AsyncClient(transport=_BilibiliChartTransport(periods, music_list))
    charts = BilibiliCharts(client)
    spec = BoardSpec(
        id="bilibili_hot",
        platform="bilibili",
        name="哔哩哔哩音乐热歌榜",
        type="hot",
        interval_sec=1800,
        extra={"list_type": 1},
    )
    items = await charts.fetch_board(spec)
    assert [item.external_id for item in items] == [
        "MA420104467149518209",
        "MA480115070962027904",
    ]
    assert [item.duration_ms for item in items] == [209_000, 84_000]
    assert items[0].official_url == (
        "https://music.bilibili.com/pc/music-detail?music_id=MA420104467149518209"
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_bilibili_catalog_lists_supported_music_charts() -> None:
    client = httpx.AsyncClient(transport=_FixtureTransport({}))
    charts = BilibiliCharts(client)
    catalog = await charts.list_catalog()
    assert catalog == [
        {
            "name": "哔哩哔哩音乐榜单",
            "charts": [
                {"key": "1", "name": "热歌榜", "playable": True},
                {"key": "3", "name": "二创榜", "playable": True},
            ],
        }
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_kugou_fixture_skips_bad_row(fixtures_dir: Path) -> None:
    payload = json.loads((fixtures_dir / "kugou_rank_song.json").read_text(encoding="utf-8"))
    client = httpx.AsyncClient(transport=_FixtureTransport(payload))
    charts = KugouCharts(client)
    spec = BoardSpec(
        id="kugou_hot",
        platform="kugou",
        name="酷狗音乐TOP500",
        type="hot",
        interval_sec=1800,
        extra={"rank_id": 8888},
    )
    items = await charts.fetch_board(spec)
    assert [item.external_id for item in items] == [
        "213d580ca0bdcc28a5fdba995ffda106",
        "3fd7e1ec51122c745c637735c8bde716",
    ]
    # The skipped row keeps its official rank, so the survivors read 1 and 3.
    assert [item.rank for item in items] == [1, 3]
    assert items[0].title == "甲乙丙丁 (你我怎么两清)"
    assert items[0].artist == "李佳薇"
    assert items[0].duration_ms == 210_000
    # The rank endpoint publishes the album id and cover, never the album name.
    assert items[0].album is None
    assert items[0].cover_url == (
        "http://imge.kugou.com/stdmusic/{size}/20260630/20260630202952972321.jpg"
    )
    assert items[0].official_url == (
        "https://www.kugou.com/song/#hash=213d580ca0bdcc28a5fdba995ffda106"
        "&album_id=197648995"
    )
    assert items[1].artist == "孙燕姿 / 某合唱"
    assert items[1].cover_url == (
        "http://imge.kugou.com/stdmusic/{size}/20250624/20250624174203375937.jpg"
    )
    await client.aclose()


def _kugou_rank_row(song_hash: str, title: str, sort: int) -> dict[str, Any]:
    return {
        "hash": song_hash,
        "songname": title,
        "sort": sort,
        "duration": 210,
        "authors": [{"author_name": "A"}],
    }


@pytest.mark.asyncio
async def test_kugou_fetches_every_rank_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.plugins.kugou.charts._PAGE_SIZE", 2)
    pages = {
        1: {
            "status": 1,
            "data": {
                "total": 5,
                "info": [
                    _kugou_rank_row("aa", "一", 1),
                    _kugou_rank_row("bb", "二", 2),
                ],
            },
        },
        2: {
            "status": 1,
            "data": {
                "total": 5,
                "info": [
                    {"songname": "坏数据"},
                    _kugou_rank_row("cc", "四", 4),
                ],
            },
        },
        3: {
            "status": 1,
            "data": {
                "total": 5,
                "info": [_kugou_rank_row("dd", "五", 5)],
            },
        },
    }
    transport = _KugouPagedSongTransport(pages)
    client = httpx.AsyncClient(transport=transport)
    charts = KugouCharts(client)
    spec = BoardSpec(
        id="kugou_hot",
        platform="kugou",
        name="酷狗音乐TOP500",
        type="hot",
        interval_sec=1800,
        extra={"rank_id": 8888},
    )
    items = await charts.fetch_board(spec)
    assert [item.external_id for item in items] == ["aa", "bb", "cc", "dd"]
    assert [item.rank for item in items] == [1, 2, 4, 5]
    assert transport.requested == [1, 2, 3]
    await client.aclose()


@pytest.mark.asyncio
async def test_kuwo_fixture_skips_bad_row(fixtures_dir: Path) -> None:
    payload = json.loads((fixtures_dir / "kuwo_bang_song.json").read_text(encoding="utf-8"))
    client = httpx.AsyncClient(transport=_FixtureTransport(payload))
    charts = KuwoCharts(client)
    spec = BoardSpec(
        id="kuwo_hot",
        platform="kuwo",
        name="酷我热歌榜",
        type="hot",
        interval_sec=1800,
        extra={"bang_id": 16},
    )
    items = await charts.fetch_board(spec)
    assert [item.external_id for item in items] == ["624683929", "567247828"]
    # Kuwo ranks by list position, so a skipped row keeps the slot it had.
    assert [item.rank for item in items] == [1, 3]
    assert items[0].title == "山风山风等等我"
    assert items[0].artist == "万海东"
    assert items[0].album == "山风山风等等我"
    assert items[0].duration_ms == 209_000
    # The bang endpoint publishes no per-song cover, only the chart's artwork.
    assert items[0].cover_url is None
    assert items[0].official_url == "https://www.kuwo.cn/play_detail/624683929"
    assert items[1].artist == "阿图&表妹"
    assert items[1].duration_ms == 243_000
    await client.aclose()


def _kuwo_bang_row(song_id: str, title: str) -> dict[str, Any]:
    return {"id": song_id, "name": title, "artist": "A", "album": "B", "song_duration": "210"}


@pytest.mark.asyncio
async def test_kuwo_fetches_every_bang_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.plugins.kuwo.charts._PAGE_SIZE", 2)
    pages = {
        0: {"num": "5", "musiclist": [_kuwo_bang_row("11", "一"), _kuwo_bang_row("22", "二")]},
        1: {"num": "5", "musiclist": [{"name": "坏数据"}, _kuwo_bang_row("44", "四")]},
        2: {"num": "5", "musiclist": [_kuwo_bang_row("55", "五")]},
    }
    transport = _KuwoBangTransport(pages)
    client = httpx.AsyncClient(transport=transport)
    charts = KuwoCharts(client)
    spec = BoardSpec(
        id="kuwo_hot",
        platform="kuwo",
        name="酷我热歌榜",
        type="hot",
        interval_sec=1800,
        extra={"bang_id": 16},
    )
    items = await charts.fetch_board(spec)
    assert [item.external_id for item in items] == ["11", "22", "44", "55"]
    assert [item.rank for item in items] == [1, 2, 4, 5]
    # Kuwo pages from zero, so the first request carries pn=0.
    assert transport.requested == [0, 1, 2]
    await client.aclose()


@pytest.mark.asyncio
async def test_kuwo_catalog_reads_the_bang_menu(fixtures_dir: Path) -> None:
    html = (fixtures_dir / "kuwo_rank_page.html").read_text(encoding="utf-8")
    client = httpx.AsyncClient(transport=_KuwoCatalogTransport(html))
    catalog = await KuwoCharts(client).list_catalog()
    assert catalog == [
        {
            "name": "官方",
            "charts": [
                # `sourceid:g` is resolved from the payload's own arguments.
                {"key": "16", "name": "酷我热歌榜", "playable": True},
                {"key": "93", "name": "酷我飙升榜", "playable": True},
            ],
        },
        {"name": "语言", "charts": [{"key": "22", "name": "酷我欧美榜", "playable": True}]},
    ]
    await client.aclose()


def test_kuwo_catalog_needs_the_rank_page_payload() -> None:
    assert parse_catalog_page("<html><body>no payload</body></html>") == []
    # A minified chart id with no matching argument is dropped instead of being
    # published as an unusable key, so its group disappears with it.
    payload = (
        "__NUXT__=(function(g){return {bangMenu:"
        '[{name:"官方",list:[{sourceid:g,intro:"x",name:"榜",id:"1"}]}]}})("");'
    )
    assert parse_catalog_page(payload) == []


@pytest.mark.asyncio
async def test_kugou_catalog_groups_ranks_by_classify(fixtures_dir: Path) -> None:
    rank_song = json.loads((fixtures_dir / "kugou_rank_song.json").read_text(encoding="utf-8"))
    rank_list = json.loads((fixtures_dir / "kugou_rank_list.json").read_text(encoding="utf-8"))
    client = httpx.AsyncClient(transport=_KugouChartTransport(rank_list, rank_song))
    charts = KugouCharts(client)
    catalog = await charts.list_catalog()
    assert catalog == [
        {"name": "热门榜", "charts": [{"key": "8888", "name": "TOP500", "playable": True}]},
        {"name": "地区榜", "charts": [{"key": "31308", "name": "内地榜", "playable": True}]},
        {"name": "曲风语种", "charts": [{"key": "59896", "name": "摇滚榜", "playable": True}]},
        {
            "name": "全球转载",
            "charts": [{"key": "4680", "name": "英国单曲榜", "playable": True}],
        },
    ]
    await client.aclose()

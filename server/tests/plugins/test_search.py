from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.domain.models import TrackQuery
from app.plugins.kugou.search import KugouSearch
from app.plugins.kugou.search import parse_search_payload as parse_kugou
from app.plugins.netease.search import NeteaseSearch
from app.plugins.netease.search import parse_search_payload as parse_netease
from app.plugins.qqmusic.search import QQMusicSearch, search_payload
from app.plugins.qqmusic.search import parse_search_payload as parse_qq

QUERY = TrackQuery(title="我不难过", artist="孙燕姿", duration_ms=320_000, limit=5)

NETEASE_PAYLOAD: dict[str, Any] = {
    "code": 200,
    "result": {
        "songs": [
            {
                "id": 287398,
                "name": "我不难过",
                "duration": 320400,
                "artists": [{"name": "孙燕姿"}],
                "album": {"name": "未完成"},
            },
            {
                "id": 34200624,
                "name": "我不难过 (Live)",
                "duration": 309106,
                "artists": [{"name": "孙燕姿"}],
            },
            {"name": "no id"},
        ]
    },
}

QQ_PAYLOAD: dict[str, Any] = {
    "code": 0,
    "req_1": {
        "code": 0,
        "data": {
            "body": {
                "song": {
                    "list": [
                        {
                            "mid": "001fsNdn1zuZnA",
                            "name": "我不难过",
                            "interval": 320,
                            "singer": [{"name": "孙燕姿"}],
                            "album": {"name": "未完成"},
                        },
                        {
                            "mid": "003QBWXL3HY5l0",
                            "name": "我不难过 (Live)",
                            "interval": 309,
                            "singer": [{"name": "孙燕姿"}],
                        },
                        {"name": "no mid"},
                    ]
                }
            }
        },
    },
}

KUGOU_PAYLOAD: dict[str, Any] = {
    "status": 1,
    "errcode": 0,
    "data": {
        "total": 371,
        "info": [
            {
                "hash": "FB572ABBEF6808C6497894899008C88D",
                "songname": "我不难过",
                "singername": "孙燕姿",
                "album_name": "My Story 2006 新歌+精选",
                "album_id": "4075477",
                "duration": 322,
                "trans_param": {"union_cover": "http://imge.kugou.com/stdmusic/{size}/a.jpg"},
            },
            {
                "hash": "4F28273873BC1E63D583D0688EC71C13",
                "songname": "我不难过 (Live)",
                "singername": "孙燕姿",
                "album_name": "飞跃红磡香港演唱会",
                "othername_original": "Live",
                "duration": 297,
                "trans_param": {
                    "union_cover": (
                        "http://singerimg.kugou.com/uploadpic/softhead/{size}/20241015/a.jpg"
                    )
                },
            },
            {"songname": "no hash"},
        ],
    },
}


def test_netease_search_payload_is_parsed_with_duration_and_album() -> None:
    tracks = parse_netease(NETEASE_PAYLOAD, limit=5)
    assert [track.external_id for track in tracks] == ["287398", "34200624"]
    assert tracks[0].platform == "netease"
    assert tracks[0].title == "我不难过"
    assert tracks[0].artist == "孙燕姿"
    assert tracks[0].album == "未完成"
    assert tracks[0].duration_ms == 320400


def test_qq_search_payload_is_parsed_in_seconds_to_milliseconds() -> None:
    tracks = parse_qq(QQ_PAYLOAD, limit=5)
    assert [track.external_id for track in tracks] == ["001fsNdn1zuZnA", "003QBWXL3HY5l0"]
    assert tracks[0].platform == "qqmusic"
    assert tracks[0].duration_ms == 320_000
    assert tracks[0].album == "未完成"


def test_kugou_search_payload_is_parsed_with_album_and_duration() -> None:
    tracks = parse_kugou(KUGOU_PAYLOAD, limit=5)
    assert [track.external_id for track in tracks] == [
        "fb572abbef6808c6497894899008c88d",
        "4f28273873bc1e63d583d0688ec71c13",
    ]
    assert tracks[0].platform == "kugou"
    assert tracks[0].title == "我不难过"
    assert tracks[0].artist == "孙燕姿"
    assert tracks[0].album == "My Story 2006 新歌+精选"
    assert tracks[0].duration_ms == 322_000
    assert tracks[0].cover_url == "http://imge.kugou.com/stdmusic/{size}/a.jpg"
    assert tracks[0].official_url == (
        "https://www.kugou.com/song/#hash=fb572abbef6808c6497894899008c88d&album_id=4075477"
    )
    assert tracks[1].version == "Live"
    assert tracks[1].cover_url == (
        "http://singerimg.kugou.com/uploadpic/softhead/{size}/20241015/a.jpg"
    )


def test_qq_search_cover_uses_gtimg_cdn() -> None:
    tracks = parse_qq(
        {
            "req_1": {
                "data": {
                    "body": {
                        "song": {
                            "list": [
                                {
                                    "mid": "001fsNdn1zuZnA",
                                    "name": "我不难过",
                                    "interval": 320,
                                    "singer": [{"name": "孙燕姿"}],
                                    "album": {"name": "未完成", "mid": "003HjGrE3Aqk4U"},
                                }
                            ]
                        }
                    }
                }
            }
        },
        limit=1,
    )
    assert tracks[0].cover_url == (
        "https://y.gtimg.cn/music/photo_new/T002R300x300M000003HjGrE3Aqk4U.jpg"
    )


@pytest.mark.parametrize("payload", [None, {}, {"result": {}}, {"result": {"songs": "nope"}}])
def test_netease_search_tolerates_unexpected_payloads(payload: object) -> None:
    assert parse_netease(payload, limit=5) == []


@pytest.mark.parametrize("payload", [None, {}, {"req_1": {"data": {}}}])
def test_qq_search_tolerates_unexpected_payloads(payload: object) -> None:
    assert parse_qq(payload, limit=5) == []


@pytest.mark.parametrize("payload", [None, {}, {"data": {}}, {"data": {"info": "nope"}}])
def test_kugou_search_tolerates_unexpected_payloads(payload: object) -> None:
    assert parse_kugou(payload, limit=5) == []


def test_qq_search_payload_sends_the_web_client_credentials() -> None:
    payload = search_payload("我不难过 孙燕姿", 5)
    assert payload["comm"]["ct"] == "19"
    assert payload["comm"]["cv"] == "1859"
    request = payload["req_1"]
    assert request["module"] == "music.search.SearchCgiService"
    assert request["param"]["query"] == "我不难过 孙燕姿"
    assert request["param"]["num_per_page"] == 5


async def test_netease_search_posts_to_cloud_search_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=NETEASE_PAYLOAD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await NeteaseSearch(client).search(QUERY)
    assert [track.external_id for track in tracks] == ["287398", "34200624"]
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/api/cloudsearch/pc"
    assert b"s=%E6%88%91%E4%B8%8D%E9%9A%BE%E8%BF%87+%E5%AD%99%E7%87%95%E5%A7%BF" in seen[0].content
    assert b"limit=5" in seen[0].content


async def test_qq_search_posts_the_search_request_with_a_referer() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=QQ_PAYLOAD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await QQMusicSearch(client).search(QUERY)
    assert [track.external_id for track in tracks] == ["001fsNdn1zuZnA", "003QBWXL3HY5l0"]
    assert seen[0].url.host == "u.y.qq.com"
    assert seen[0].headers["referer"] == "https://y.qq.com/"
    assert b"DoSearchForQQMusicDesktop" in seen[0].content


async def test_kugou_search_requests_the_v3_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=KUGOU_PAYLOAD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await KugouSearch(client).search(QUERY)
    assert [track.external_id for track in tracks] == [
        "fb572abbef6808c6497894899008c88d",
        "4f28273873bc1e63d583d0688ec71c13",
    ]
    assert seen[0].method == "GET"
    assert seen[0].url.host == "mobiles.kugou.com"
    assert seen[0].url.path == "/api/v3/search/song"
    assert seen[0].url.params["keyword"] == "我不难过 孙燕姿"
    assert seen[0].url.params["pagesize"] == "5"
    assert seen[0].headers["referer"] == "https://www.kugou.com/"


async def test_search_skips_the_network_when_the_title_is_empty() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=NETEASE_PAYLOAD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await NeteaseSearch(client).search(TrackQuery(title="", artist="")) == []
        assert await QQMusicSearch(client).search(TrackQuery(title="", artist="")) == []
        assert await KugouSearch(client).search(TrackQuery(title="", artist="")) == []
    assert calls == 0

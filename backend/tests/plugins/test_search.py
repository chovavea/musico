from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.domain.models import TrackQuery
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


@pytest.mark.parametrize("payload", [None, {}, {"result": {}}, {"result": {"songs": "nope"}}])
def test_netease_search_tolerates_unexpected_payloads(payload: object) -> None:
    assert parse_netease(payload, limit=5) == []


@pytest.mark.parametrize("payload", [None, {}, {"req_1": {"data": {}}}])
def test_qq_search_tolerates_unexpected_payloads(payload: object) -> None:
    assert parse_qq(payload, limit=5) == []


def test_qq_search_payload_sends_the_web_client_credentials() -> None:
    payload = search_payload("我不难过 孙燕姿", 5)
    assert payload["comm"]["ct"] == "19"
    assert payload["comm"]["cv"] == "1859"
    request = payload["req_1"]
    assert request["module"] == "music.search.SearchCgiService"
    assert request["param"]["query"] == "我不难过 孙燕姿"
    assert request["param"]["num_per_page"] == 5


async def test_netease_search_calls_the_public_search_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=NETEASE_PAYLOAD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await NeteaseSearch(client).search(QUERY)
    assert [track.external_id for track in tracks] == ["287398", "34200624"]
    assert seen[0].url.path == "/api/search/get"
    assert seen[0].url.params["s"] == "我不难过 孙燕姿"
    assert seen[0].url.params["limit"] == "5"


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


async def test_search_skips_the_network_when_the_title_is_empty() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=NETEASE_PAYLOAD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await NeteaseSearch(client).search(TrackQuery(title="", artist="")) == []
        assert await QQMusicSearch(client).search(TrackQuery(title="", artist="")) == []
    assert calls == 0

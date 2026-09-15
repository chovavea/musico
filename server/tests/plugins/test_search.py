from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from app.domain.models import TrackQuery
from app.plugins.kugou.search import KugouSearch
from app.plugins.kugou.search import parse_search_payload as parse_kugou
from app.plugins.kugou.search import search_params as kugou_params
from app.plugins.kuwo.search import KuwoSearch
from app.plugins.kuwo.search import parse_search_payload as parse_kuwo
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

# Kuwo answers this endpoint with a JavaScript literal instead of JSON, and it
# escapes an ampersand twice, so the raw body carries `\\\\u0026`.
KUWO_PAYLOAD = (
    r"""{'ARTISTPIC':'','HIT':'3856','HITMODE':'song','PN':'0','RN':'3','abslist':["""
    r"""{'AARTIST':'Jay&nbsp;Chou','ALBUM':'','ALBUMID':'0','ARTIST':'周杰伦',"""
    r"""'ARTISTID':'336','DURATION':'269','MUSICRID':'MUSIC_51685512',"""
    r"""'NAME':'晴天&nbsp;(KTV版伴奏)','web_albumpic_short':'120/54/93/1964735275.jpg',"""
    r"""'web_artistpic_short':'120/s4s56/58/291211030.jpg'},"""
    r"""{'ARTIST':'周杰伦\\\\u0026五月天','ALBUM':'','DURATION':'787',"""
    r"""'MUSICRID':'MUSIC_152809941','NAME':'志明与春娇+听妈妈的话','web_albumpic_short':''},"""
    r"""{'NAME':'no rid','ARTIST':'x'}]}"""
)


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


def qq_page(start: int, count: int) -> dict[str, Any]:
    return {
        "code": 0,
        "req_1": {
            "code": 0,
            "data": {
                "body": {
                    "song": {
                        "list": [
                            {
                                "mid": f"mid-{start + index:03d}",
                                "name": f"我不难过 {start + index}",
                                "interval": 320,
                                "singer": [{"name": "孙燕姿"}],
                                "album": {"name": "未完成"},
                            }
                            for index in range(count)
                        ]
                    }
                }
            },
        },
    }


async def test_qq_search_pages_past_the_sixty_item_page_cap() -> None:
    """num_per_page above 60 makes QQ answer with an empty song list."""
    params: list[tuple[int, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        param = json.loads(request.content)["req_1"]["param"]
        page = int(param["page_num"])
        params.append((page, int(param["num_per_page"])))
        return httpx.Response(200, json=qq_page((page - 1) * 60, 60 if page == 1 else 10))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await QQMusicSearch(client).search(QUERY.model_copy(update={"limit": 70}))

    assert len(tracks) == 70
    assert [track.external_id for track in tracks[:2]] == ["mid-000", "mid-001"]
    assert [track.external_id for track in tracks[-1:]] == ["mid-069"]
    # Pages are requested together, so only their set is stable.
    assert sorted(params) == [(1, 60), (2, 60)]


async def test_qq_search_stops_when_the_api_repeats_a_page() -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=qq_page(0, 60))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await QQMusicSearch(client).search(QUERY.model_copy(update={"limit": 70}))

    assert len(tracks) == 60
    assert len(calls) == 2


async def test_qq_search_requests_its_pages_concurrently() -> None:
    """Both pages must be in flight at once; a serial version deadlocks here."""
    arrived = 0
    both_arrived = asyncio.Event()

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            both_arrived.set()
        await asyncio.wait_for(both_arrived.wait(), timeout=1.0)
        return httpx.Response(200, json=qq_page(0, 60))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await QQMusicSearch(client).search(QUERY.model_copy(update={"limit": 100}))

    assert arrived == 2
    assert len(tracks) == 60


async def test_qq_search_reports_a_throttled_response_as_a_failure() -> None:
    """HTTP 200 with code 2001 and no songs means throttled, not "no matches"."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "req_1": {"code": 2001}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await QQMusicSearch(client).search(QUERY.model_copy(update={"limit": 100}))


async def test_qq_search_keeps_an_empty_result_a_success() -> None:
    """A genuine miss is code 0 with an empty list and must not fail."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=qq_page(0, 0))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await QQMusicSearch(client).search(QUERY.model_copy(update={"limit": 100}))

    assert tracks == []


async def test_qq_search_keeps_the_first_page_when_a_later_page_is_throttled() -> None:
    """A throttled second page must not discard the songs already in hand."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(json.loads(request.content)["req_1"]["param"]["page_num"])
        if page == 2:
            return httpx.Response(200, json={"code": 0, "req_1": {"code": 2001}})
        return httpx.Response(200, json=qq_page(0, 60))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await QQMusicSearch(client).search(QUERY.model_copy(update={"limit": 100}))

    assert len(tracks) == 60
    assert tracks[0].external_id == "mid-000"


async def test_qq_search_keeps_an_empty_first_page_when_a_later_page_fails() -> None:
    """A genuine miss on page 1 is still a miss, even if page 2 is throttled."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(json.loads(request.content)["req_1"]["param"]["page_num"])
        if page == 1:
            return httpx.Response(200, json=qq_page(0, 0))
        return httpx.Response(200, json={"code": 0, "req_1": {"code": 2001}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await QQMusicSearch(client).search(QUERY.model_copy(update={"limit": 100}))

    assert tracks == []


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


def kugou_page(start: int, count: int) -> dict[str, Any]:
    return {
        "data": {
            "info": [
                {
                    "hash": f"hash-{start + index:03d}",
                    "songname": f"我不难过 {start + index}",
                    "singername": "孙燕姿",
                    "album_name": "未完成",
                    "duration": 320,
                }
                for index in range(count)
            ]
        }
    }


async def test_kugou_search_pages_past_the_thirty_item_page_cap() -> None:
    """The v3 endpoint ignores pagesize above 30 and answers with 30 rows."""
    params: list[tuple[int, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        params.append((page, int(request.url.params["pagesize"])))
        return httpx.Response(200, json=kugou_page((page - 1) * 30, 30 if page < 3 else 10))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await KugouSearch(client).search(QUERY.model_copy(update={"limit": 70}))

    assert len(tracks) == 70
    assert [track.external_id for track in tracks[:2]] == ["hash-000", "hash-001"]
    assert [track.external_id for track in tracks[-1:]] == ["hash-069"]
    # Pages are requested together, so only their set is stable.
    assert sorted(params) == [(1, 30), (2, 30), (3, 30)]


async def test_kugou_search_stops_when_the_api_repeats_a_page() -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=kugou_page(0, 30))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await KugouSearch(client).search(QUERY.model_copy(update={"limit": 70}))

    assert len(tracks) == 30
    # 70 items need three pages of 30, all requested up front; the repeats are
    # dropped by the de-duplication instead of stopping the paging early.
    assert len(calls) == 3


async def test_kugou_search_requests_its_pages_concurrently() -> None:
    """Every page must be in flight at once; a serial version deadlocks here."""
    arrived = 0
    all_arrived = asyncio.Event()

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal arrived
        arrived += 1
        if arrived == 4:
            all_arrived.set()
        await asyncio.wait_for(all_arrived.wait(), timeout=1.0)
        return httpx.Response(200, json=kugou_page(0, 30))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await KugouSearch(client).search(QUERY.model_copy(update={"limit": 100}))

    assert arrived == 4
    assert len(tracks) == 30


async def test_kugou_search_reports_a_failed_envelope_as_a_failure() -> None:
    """status != 1 carries a throttled or rejected request, not an empty result."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 0, "errcode": 20001, "error": "被限流"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await KugouSearch(client).search(QUERY.model_copy(update={"limit": 100}))


async def test_kugou_search_keeps_an_empty_result_a_success() -> None:
    """status 1 with errcode 0 and no rows is a real miss and must not fail."""
    payload = {"status": 1, "errcode": 0, "error": "", "data": {"info": []}}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await KugouSearch(client).search(QUERY.model_copy(update={"limit": 100}))

    assert tracks == []


async def test_kugou_search_keeps_the_first_page_when_a_later_page_is_rejected() -> None:
    """A failed later page must not discard songs already fetched."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        if page > 1:
            return httpx.Response(200, json={"status": 0, "errcode": 20001, "error": "被限流"})
        return httpx.Response(200, json=kugou_page(0, 30))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await KugouSearch(client).search(QUERY.model_copy(update={"limit": 70}))

    assert len(tracks) == 30
    assert tracks[0].external_id == "hash-000"


def test_kuwo_search_payload_is_parsed_from_the_js_literal() -> None:
    tracks = parse_kuwo(KUWO_PAYLOAD, limit=5)
    assert [track.external_id for track in tracks] == ["51685512", "152809941"]
    assert tracks[0].platform == "kuwo"
    assert tracks[0].title == "晴天 (KTV版伴奏)"
    assert tracks[0].artist == "周杰伦"
    assert tracks[0].duration_ms == 269_000
    assert tracks[0].cover_url == (
        "https://img1.kuwo.cn/star/albumcover/120/54/93/1964735275.jpg"
    )
    assert tracks[0].official_url == "https://www.kuwo.cn/play_detail/51685512"
    # Kuwo publishes no album on this endpoint, only for some rows at all.
    assert tracks[1].artist == "周杰伦&五月天"
    assert tracks[1].album is None
    assert tracks[1].cover_url is None


def test_kuwo_search_also_reads_a_json_body() -> None:
    tracks = parse_kuwo(
        {
            "abslist": [
                {"MUSICRID": "MUSIC_646859398", "NAME": "大梦归", "ARTIST": "周深", "DURATION": 229}
            ]
        },
        limit=1,
    )
    assert [track.external_id for track in tracks] == ["646859398"]
    assert tracks[0].duration_ms == 229_000


def test_kuwo_search_cover_strips_a_leading_slash() -> None:
    tracks = parse_kuwo(
        {
            "abslist": [
                {
                    "MUSICRID": "MUSIC_51685512",
                    "NAME": "晴天",
                    "ARTIST": "周杰伦",
                    "web_albumpic_short": "/120/s4s75/33/1791348220.jpg",
                }
            ]
        },
        limit=1,
    )
    assert tracks[0].cover_url == (
        "https://img1.kuwo.cn/star/albumcover/120/s4s75/33/1791348220.jpg"
    )


@pytest.mark.parametrize(
    "short",
    [
        "https://img1.kuwo.cn/star/albumcover/120/54/93/1964735275.jpg",
        "s4s56/58/291211030.jpg",
        "120/../54/93/1964735275.jpg",
        "120/54/93/1964735275.jpg?x=1",
    ],
)
def test_kuwo_search_drops_cover_paths_the_proxy_would_reject(short: str) -> None:
    tracks = parse_kuwo(
        {
            "abslist": [
                {
                    "MUSICRID": "MUSIC_51685512",
                    "NAME": "晴天",
                    "ARTIST": "周杰伦",
                    "web_albumpic_short": short,
                }
            ]
        },
        limit=1,
    )
    assert tracks[0].cover_url is None


def test_kuwo_search_respects_the_limit() -> None:
    assert len(parse_kuwo(KUWO_PAYLOAD, limit=1)) == 1


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


@pytest.mark.parametrize("payload", [None, {}, "", "not a payload", "['list']"])
def test_kuwo_search_tolerates_unexpected_payloads(payload: object) -> None:
    assert parse_kuwo(payload, limit=5) == []


def test_qq_search_payload_sends_the_web_client_credentials() -> None:
    payload = search_payload("我不难过 孙燕姿", 5)
    assert payload["comm"]["ct"] == "19"
    assert payload["comm"]["cv"] == "1859"
    request = payload["req_1"]
    assert request["module"] == "music.search.SearchCgiService"
    assert request["param"]["query"] == "我不难过 孙燕姿"
    assert request["param"]["num_per_page"] == 5
    assert request["param"]["page_num"] == 1
    # The API returns nothing above 60 per page, so the request is capped and
    # the remaining results have to come from later pages.
    assert search_payload("我不难过 孙燕姿", 100)["req_1"]["param"]["num_per_page"] == 60
    assert search_payload("我不难过 孙燕姿", 100, page=3)["req_1"]["param"]["page_num"] == 3


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
    # The endpoint caps a page at 30 rows, so bigger limits are paged.
    assert kugou_params("我不难过 孙燕姿", 100)["pagesize"] == 30
    assert kugou_params("我不难过 孙燕姿", 100, page=4)["page"] == 4


async def test_kuwo_search_requests_the_legacy_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=KUWO_PAYLOAD.encode("utf-8"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await KuwoSearch(client).search(QUERY)
    assert [track.external_id for track in tracks] == ["51685512", "152809941"]
    assert seen[0].method == "GET"
    assert seen[0].url.host == "search.kuwo.cn"
    assert seen[0].url.path == "/r.s"
    assert seen[0].url.params["all"] == "我不难过 孙燕姿"
    assert seen[0].url.params["rn"] == "5"
    # Without encoding=utf8 Kuwo answers GBK, which would mangle every title.
    assert seen[0].url.params["encoding"] == "utf8"
    assert seen[0].headers["referer"] == "https://www.kuwo.cn/"


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
        assert await KuwoSearch(client).search(TrackQuery(title="", artist="")) == []
    assert calls == 0

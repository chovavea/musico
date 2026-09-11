from __future__ import annotations

import json
from pathlib import Path

import httpx
from app.adapters.http.preview import _open_audio, host_allowed
from app.domain.models import TrackRef
from app.plugins.bilibili.preview import (
    BilibiliPreview,
)
from app.plugins.bilibili.preview import (
    parse_detail_payload as parse_bilibili_detail,
)
from app.plugins.bilibili.preview import (
    parse_preview_payload as parse_bilibili_preview,
)
from app.plugins.netease.preview import official_outer_url
from app.plugins.qqmusic.preview import (
    QQMusicPreview,
    parse_qq_preview_url,
    vkey_filename,
    vkey_payload,
)


def test_vkey_filename_format() -> None:
    assert vkey_filename("003oL5WM25NJtt", "M500", ".mp3") == "M500003oL5WM25NJtt003oL5WM25NJtt.mp3"
    assert vkey_filename("003oL5WM25NJtt", "C400", ".m4a") == "C400003oL5WM25NJtt003oL5WM25NJtt.m4a"


def test_vkey_payload_is_anonymous_shape() -> None:
    filename = vkey_filename("003oL5WM25NJtt", "M500", ".mp3")
    payload = vkey_payload("003oL5WM25NJtt", filename)
    param = payload["req_1"]["param"]
    assert param["loginflag"] == 1
    assert param["uin"] == "0"
    assert param["filename"] == [filename]
    assert payload["loginUin"] == "0"
    assert "authst" not in payload["comm"]


def test_parse_qq_preview_joins_sip_and_purl() -> None:
    url = parse_qq_preview_url(
        {
            "req_1": {
                "data": {
                    "sip": ["https://ws.stream.qqmusic.qq.com/"],
                    "midurlinfo": [{"purl": "C400abc.m4a?vkey=1"}],
                }
            }
        }
    )
    assert url == "https://ws.stream.qqmusic.qq.com/C400abc.m4a?vkey=1"


def test_parse_qq_preview_empty_purl() -> None:
    assert (
        parse_qq_preview_url(
            {"req_1": {"data": {"sip": ["https://x/"], "midurlinfo": [{"purl": ""}]}}}
        )
        is None
    )


def test_parse_qq_preview_skips_ws_sip() -> None:
    url = parse_qq_preview_url(
        {
            "req_1": {
                "data": {
                    "sip": ["http://ws.stream.qqmusic.qq.com/", "https://isure.stream.qqmusic.qq.com/"],
                    "midurlinfo": [{"purl": "M500abc.mp3?vkey=1"}],
                }
            }
        }
    )
    assert url == "https://isure.stream.qqmusic.qq.com/M500abc.mp3?vkey=1"


def test_netease_outer_url() -> None:
    assert official_outer_url("186016") == "https://music.163.com/song/media/outer/url?id=186016.mp3"


def test_preview_host_allowlist() -> None:
    assert host_allowed("ws.stream.qqmusic.qq.com")
    assert host_allowed("m801.music.126.net")
    assert host_allowed("music.163.com")
    assert host_allowed("upos-sz-mirrorcos.bilivideo.com")
    assert not host_allowed("evil.example.com")
    assert not host_allowed("qq.com")


def test_bilibili_detail_payload_parses_official_player_info() -> None:
    assert parse_bilibili_detail(
        {
            "code": 0,
            "data": {
                "support_listen": True,
                "mv_aid": 123456789,
                "mv_cid": 987654321,
                "mv_bvid": "BV1xx411c7mD",
            },
        }
    ) == (123456789, 987654321, "BV1xx411c7mD")


def test_bilibili_detail_payload_rejects_unplayable_track() -> None:
    assert parse_bilibili_detail(
        {
            "code": 0,
            "data": {
                "support_listen": False,
                "mv_aid": 123456789,
                "mv_cid": 987654321,
            },
        }
    ) is None


def test_bilibili_preview_payload_parses_durl() -> None:
    assert parse_bilibili_preview(
        {
            "code": 0,
            "data": {
                "durl": [
                    {
                        "url": (
                            "https://upos-sz-estgcos.bilivideo.com/"
                            "upgcxcode/example.mp4"
                        )
                    }
                ],
            },
        }
    ) == "https://upos-sz-estgcos.bilivideo.com/upgcxcode/example.mp4"


def test_bilibili_preview_payload_rejects_missing_durl() -> None:
    assert parse_bilibili_preview({"code": 0, "data": {"durl": []}}) is None


async def test_bilibili_preview_requests_official_player_url(fixtures_dir: Path) -> None:
    detail_payload = json.loads(
        (fixtures_dir / "bilibili_detail.json").read_text(encoding="utf-8")
    )
    playurl_payload = json.loads(
        (fixtures_dir / "bilibili_playurl.json").read_text(encoding="utf-8")
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/bgm/detail"):
            return httpx.Response(200, json=detail_payload)
        return httpx.Response(200, json=playurl_payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        info = await BilibiliPreview(client).preview(
            TrackRef(
                platform="bilibili",
                external_id="MA420104467149518209",
                title="t",
                artist="a",
            )
        )

    assert seen[0].url.path.endswith("/bgm/detail")
    assert seen[0].url.params["music_id"] == "MA420104467149518209"
    assert seen[0].headers["referer"] == "https://music.bilibili.com/pc/rank"
    assert seen[1].url.path.endswith("/player/playurl")
    assert seen[1].url.params["avid"] == "123456789"
    assert seen[1].url.params["cid"] == "987654321"
    assert seen[1].url.params["qn"] == "16"
    assert seen[1].url.params["fnval"] == "0"
    assert seen[1].headers["referer"] == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert info.preview_url == "https://upos-sz-estgcos.bilivideo.com/upgcxcode/example.mp4"
    assert info.quality == "low"


async def test_open_audio_accepts_bilibili_mp4_as_audio() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "video/mp4"},
            content=b"\x00\x00\x00\x18ftypmp42",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await _open_audio(
            client,
            "https://upos-sz-estgcos.bilivideo.com/upgcxcode/example.mp4",
            {},
            ("bilivideo.com",),
            range_header=None,
            media_type="audio/mp4",
        )
        assert response is not None
        assert response.media_type == "audio/mp4"
        assert [chunk async for chunk in response.body_iterator] == [b"\x00\x00\x00\x18ftypmp42"]


async def test_open_audio_rejects_mp4_for_non_bilibili_audio() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "video/mp4"},
            content=b"\x00\x00\x00\x18ftypmp42",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await _open_audio(
            client,
            "https://upos-sz-estgcos.bilivideo.com/upgcxcode/example.mp4",
            {},
            ("bilivideo.com",),
            range_header=None,
            media_type="audio/mpeg",
        )
        assert response is None


async def test_qq_preview_posts_m500_then_c400() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        filename = body["req_1"]["param"]["filename"][0]
        calls.append(filename)
        if filename.startswith("M500"):
            return httpx.Response(
                200,
                json={"req_1": {"data": {"sip": ["https://x/"], "midurlinfo": [{"purl": ""}]}}},
            )
        return httpx.Response(
            200,
            json={
                "req_1": {
                    "data": {
                        "sip": ["https://x/"],
                        "midurlinfo": [{"purl": "C400x.m4a"}],
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        info = await QQMusicPreview(client).preview(
            TrackRef(platform="qqmusic", external_id="abc", title="t", artist="a")
        )

    assert [name[:4] for name in calls] == ["M500", "C400"]
    assert info.preview_url == "https://x/C400x.m4a"
    assert info.quality == "low"

from __future__ import annotations

import json

import httpx

from app.adapters.http.preview import host_allowed
from app.domain.models import TrackRef
from app.plugins.netease.preview import official_outer_url
from app.plugins.qqmusic.preview import QQMusicPreview, parse_qq_preview_url, vkey_filename, vkey_payload


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
    assert parse_qq_preview_url({"req_1": {"data": {"sip": ["https://x/"], "midurlinfo": [{"purl": ""}]}}}) is None


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
    assert not host_allowed("evil.example.com")
    assert not host_allowed("qq.com")


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
            json={"req_1": {"data": {"sip": ["https://x/"], "midurlinfo": [{"purl": "C400x.m4a"}]}}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        info = await QQMusicPreview(client).preview(
            TrackRef(platform="qqmusic", external_id="abc", title="t", artist="a")
        )

    assert [name[:4] for name in calls] == ["M500", "C400"]
    assert info.preview_url == "https://x/C400x.m4a"
    assert info.quality == "low"

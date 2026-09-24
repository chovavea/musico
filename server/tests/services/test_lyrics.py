from __future__ import annotations

import base64
import json

import httpx
import pytest
from app.services.lyrics import LyricsService, LyricsUnavailable, parse_lrc


def test_parse_lrc_keeps_every_timestamp_and_applies_offset() -> None:
    text = "\n".join(
        [
            "[ti:晴天]",
            "[offset:500]",
            "[00:01.00]第一句",
            "[00:02.50][00:03.00]重复一句",
            "[00:04] ",
        ]
    )
    lines = parse_lrc(text)
    assert [line["text"] for line in lines] == ["第一句", "重复一句", "重复一句"]
    assert [line["time_ms"] for line in lines] == [1500, 3000, 3500]


@pytest.mark.asyncio
async def test_netease_lyrics_merge_a_translation_onto_the_same_line() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["id"] == "186016"
        body = {
            "lrc": {"lyric": "[00:01.00]晴天\n[00:05.00]故事"},
            "tlyric": {"lyric": "[00:01.20]Sunny day\n[00:09.00]太远了"},
        }
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await LyricsService(client).lookup("netease", "186016", title="晴天")
    assert payload["synced"] is True
    assert payload["lines"][0]["translation"] == "Sunny day"
    assert payload["lines"][1]["translation"] is None


@pytest.mark.asyncio
async def test_kugou_lyrics_decode_the_lrc_download() -> None:
    lrc = "[00:01.00]山风\n[00:02.00]等等我"
    encoded = base64.b64encode(lrc.encode("utf-8")).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={"candidates": [{"id": "1", "accesskey": "key", "score": 10}]},
            )
        assert request.url.params["fmt"] == "lrc"
        return httpx.Response(200, json={"content": encoded, "fmt": "lrc"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await LyricsService(client).lookup(
            "kugou", "abc", title="山风", artist="万海东", duration_ms=180000
        )
    assert [line["text"] for line in payload["lines"]] == ["山风", "等等我"]


@pytest.mark.asyncio
async def test_kuwo_lyrics_use_the_line_timestamps() -> None:
    body = {
        "data": {
            "lrclist": [
                {"time": "1.5", "lineLyric": "第一句"},
                {"time": "0.2", "lineLyric": "开头"},
            ]
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["musicId"] == "99"
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await LyricsService(client).lookup("kuwo", "99")
    assert [line["time_ms"] for line in payload["lines"]] == [200, 1500]


@pytest.mark.asyncio
async def test_qq_lyrics_accept_a_jsonp_wrapper() -> None:
    payload = {"lyric": "[00:01.00]茶汤", "trans": ""}
    raw = "MusicJsonCallback(" + json.dumps(payload) + ")"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=raw)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await LyricsService(client).lookup("qqmusic", "mid")
    assert result["lines"][0]["text"] == "茶汤"


@pytest.mark.asyncio
async def test_instrumental_marker_is_not_treated_as_synced_lyrics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"lrc": {"lyric": "[00:01.00]纯音乐，请欣赏"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await LyricsService(client).lookup("netease", "1")
    assert payload["synced"] is False
    assert payload["lines"] == [{"time_ms": None, "text": "纯音乐，请欣赏", "translation": None}]


@pytest.mark.asyncio
async def test_upstream_failure_is_not_stored_as_an_empty_lyric() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"lrc": {"lyric": "[00:01.00]晴天"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = LyricsService(client)
        with pytest.raises(LyricsUnavailable):
            await service.lookup("netease", "1")
        payload = await service.lookup("netease", "1")
    assert payload["lines"][0]["text"] == "晴天"
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_missing_bilibili_lyric_is_an_empty_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"mv_lyric": ""}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await LyricsService(client).lookup("bilibili", "MA1")
    assert payload["lines"] == []
    assert payload["synced"] is False

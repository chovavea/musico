from __future__ import annotations

from urllib.parse import quote

import httpx
import pytest
from app.domain.matching import is_auto_match, is_fuzzy_preview_match
from app.domain.models import TrackRef
from app.fallback.gequbao import (
    GequbaoPreview,
    _play_id_from_page,
    _rewrite_playback_url,
    _search_keywords,
    _song_hits,
    _validated_playback_url,
)

BASE_URL = "https://music.example"
PLAY_URL = "https://kw-er.kuwo.cn/token/resource/30106/trackmedia/M500003aAYrm3GE0Ac.mp3"
FETCHABLE_URL = "https://kw-lv.kuwo.cn/token/resource/30106/trackmedia/M500003aAYrm3GE0Ac.mp3"
SEARCH_HTML = """
<div class="row no-gutters py-2d5 border-top align-items-center">
  <div class="col-9 col-md-8">
    <a href="/music/207883" class="hover-zoom d-block text-decoration-none"
       title="稻香 - 大宥"></a>
  </div>
  <div class="col-3 col-md-4 text-right">
    <a href="/music/207883" target="_blank" title="稻香 - 大宥">播放&下载</a>
  </div>
</div>
<div class="row no-gutters py-2d5 border-top align-items-center">
  <div class="col-9 col-md-8">
    <a href="/music/4190" class="hover-zoom d-block text-decoration-none"
       title="稻香 - 周杰伦"></a>
  </div>
  <div class="col-3 col-md-4 text-right">
    <a href="/music/4190" target="_blank" title="稻香 - 周杰伦">播放&下载</a>
  </div>
</div>
<div class="row no-gutters py-2d5 border-top align-items-center">
  <div class="col-9 col-md-8">
    <a href="/music/19659" class="hover-zoom d-block text-decoration-none"
       title="稻香 - 周杰伦&amp;派伟俊"></a>
  </div>
</div>
"""


def _music_html(play_id: str = "PLAY4190") -> str:
    payload = (
        r"{\u0022play_id\u0022:\u0022"
        + play_id
        + r"\u0022,\u0022mp3_title\u0022:\u0022\\u7a3b\\u9999\u0022,"
        r"\u0022mp3_author\u0022:\u0022\\u5468\\u6770\\u4f26\u0022}"
    )
    return f"<html><script>window.appData = JSON.parse('{payload}');</script></html>"


async def _offline_guard(_url: str, _hosts: object) -> None:
    return None


def _track() -> TrackRef:
    return TrackRef(platform="qqmusic", external_id="q1", title="稻香", artist="周杰伦")


def test_search_parser_reads_title_and_artist() -> None:
    hits = _song_hits(SEARCH_HTML)
    assert [(hit.song_id, hit.title, hit.artist) for hit in hits] == [
        ("207883", "稻香", "大宥"),
        ("4190", "稻香", "周杰伦"),
        ("19659", "稻香", "周杰伦&派伟俊"),
    ]


def test_appdata_reads_the_encrypted_play_id() -> None:
    assert _play_id_from_page(_music_html("eyJplay")) == "eyJplay"


def test_search_keywords_flatten_featured_artist_slashes() -> None:
    track = TrackRef(
        platform="kugou",
        external_id="x",
        title="茶花开了，该回家了",
        artist="王睿卓 / 加木",
    )
    keywords = _search_keywords(track)
    assert keywords[0] == "茶花开了，该回家了 王睿卓 加木"
    assert "/" not in "".join(keywords)


def test_anti_leech_node_is_rewritten_to_a_fetchable_host() -> None:
    assert (
        _rewrite_playback_url("https://kw-er.kuwo.cn/x.mp3?bitrate$128&from=vip")
        == "https://kw-lv.kuwo.cn/x.mp3?bitrate$128&from=vip"
    )
    assert _rewrite_playback_url("https://kw-bj.kuwo.cn/x.mp3") == "https://kw-bj.kuwo.cn/x.mp3"


def test_playurl_rejects_an_off_allowlist_host() -> None:
    assert (
        _validated_playback_url(PLAY_URL, ("kuwo.cn",))
        == "https://kw-er.kuwo.cn/token/resource/30106/trackmedia/M500003aAYrm3GE0Ac.mp3"
    )
    assert (
        _validated_playback_url(
            "https://kw-er.kuwo.cn/x.mp3?bitrate$128&from=vip", ("kuwo.cn",)
        )
        == "https://kw-er.kuwo.cn/x.mp3?bitrate$128&from=vip"
    )
    assert _validated_playback_url("https://evil.example/x.mp3", ("kuwo.cn",)) is None
    assert _validated_playback_url("http://kw-er.kuwo.cn/x.mp3", ("kuwo.cn",)) is None


@pytest.mark.asyncio
async def test_preview_skips_a_cover_and_posts_play_id() -> None:
    seen: list[str] = []
    posted: list[dict[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url}")
        if request.url.path.startswith("/s/"):
            return httpx.Response(200, text=SEARCH_HTML)
        if request.url.path == "/music/4190":
            return httpx.Response(200, text=_music_html())
        if request.url.path == "/member/common-play-url":
            posted.append(dict(pair.split("=", 1) for pair in request.content.decode().split("&")))
            assert request.headers.get("x-requested-with") == "XMLHttpRequest"
            assert str(request.headers.get("referer")).endswith("/music/4190")
            return httpx.Response(
                200,
                json={"code": 1, "data": {"url": PLAY_URL, "is_white_url": False}, "msg": "ok"},
            )
        if request.url.path == "/music/207883":
            raise AssertionError("cover track should not be opened")
        return httpx.Response(404, text="missing")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = GequbaoPreview(client, BASE_URL, url_guard=_offline_guard, max_candidates=1)
        clips = [clip async for clip in source.iter_preview_clips(_track())]

    assert [clip.source_track_id for clip in clips] == ["/music/4190"]
    assert clips[0].url == FETCHABLE_URL
    assert clips[0].media_type == "audio/mpeg"
    assert posted == [{"id": "PLAY4190", "purpose": "play"}]
    assert any(f"/s/{quote('稻香 周杰伦', safe='')}" in url for url in seen)


@pytest.mark.asyncio
async def test_preview_skips_captcha_and_quota_gates() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/s/"):
            return httpx.Response(200, text=SEARCH_HTML)
        if request.url.path == "/music/4190":
            return httpx.Response(200, text=_music_html())
        if request.url.path == "/member/common-play-url":
            return httpx.Response(200, json={"code": 2, "msg": "captcha"})
        return httpx.Response(404, text="missing")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = GequbaoPreview(client, BASE_URL, url_guard=_offline_guard, max_candidates=1)
        clips = [clip async for clip in source.iter_preview_clips(_track())]

    assert clips == []


@pytest.mark.asyncio
async def test_preview_tries_title_only_after_a_failed_full_keyword() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.startswith("/s/"):
            if quote("加木", safe="") in str(request.url):
                return httpx.Response(404, text="missing")
            return httpx.Response(
                200,
                text=SEARCH_HTML.replace("稻香", "茶花开了，该回家了")
                .replace("周杰伦", "王睿卓 / 加木")
                .replace("大宥", "别人"),
            )
        if request.url.path.startswith("/music/"):
            return httpx.Response(200, text=_music_html())
        if request.url.path == "/member/common-play-url":
            return httpx.Response(
                200,
                json={"code": 1, "data": {"url": PLAY_URL, "is_white_url": False}, "msg": "ok"},
            )
        return httpx.Response(404, text="missing")

    track = TrackRef(
        platform="kugou",
        external_id="x",
        title="茶花开了，该回家了",
        artist="王睿卓 / 加木",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = GequbaoPreview(client, BASE_URL, url_guard=_offline_guard, max_candidates=1)
        clips = [clip async for clip in source.iter_preview_clips(track)]

    assert len(clips) == 1
    encoded_full = quote("茶花开了，该回家了 王睿卓 加木", safe="")
    encoded_title = quote("茶花开了，该回家了", safe="")
    assert any(encoded_full in url for url in seen)
    assert any(encoded_title in url and encoded_full not in url for url in seen)


@pytest.mark.asyncio
async def test_fuzzy_preview_prefers_the_original_artist_over_a_cover() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/s/"):
            return httpx.Response(200, text=SEARCH_HTML)
        if request.url.path == "/music/4190":
            return httpx.Response(200, text=_music_html())
        if request.url.path == "/member/common-play-url":
            return httpx.Response(
                200,
                json={"code": 1, "data": {"url": PLAY_URL, "is_white_url": False}, "msg": "ok"},
            )
        if request.url.path == "/music/207883":
            raise AssertionError("cover track should not be preferred")
        return httpx.Response(404, text="missing")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = GequbaoPreview(client, BASE_URL, url_guard=_offline_guard, max_candidates=1)
        clips = [
            clip
            async for clip in source.iter_preview_clips(
                _track(), match=is_fuzzy_preview_match
            )
        ]

    assert [clip.source_track_id for clip in clips] == ["/music/4190"]


@pytest.mark.asyncio
async def test_fuzzy_preview_matches_a_parenthetical_artist_alias() -> None:
    html = (
        SEARCH_HTML.replace("稻香", "Whiplash")
        .replace("周杰伦", "aespa")
        .replace("大宥", "别人")
    )
    track = TrackRef(
        platform="kugou",
        external_id="k1",
        title="Whiplash (NINGNING Solo)",
        artist="aespa (에스파)",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/s/"):
            return httpx.Response(200, text=html)
        if request.url.path == "/music/4190":
            return httpx.Response(200, text=_music_html())
        if request.url.path == "/member/common-play-url":
            return httpx.Response(
                200,
                json={"code": 1, "data": {"url": PLAY_URL, "is_white_url": False}, "msg": "ok"},
            )
        return httpx.Response(404, text="missing")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = GequbaoPreview(client, BASE_URL, url_guard=_offline_guard, max_candidates=1)
        strict = [clip async for clip in source.iter_preview_clips(track)]
        fuzzy = [
            clip
            async for clip in source.iter_preview_clips(
                track, match=is_fuzzy_preview_match
            )
        ]

    assert strict == []
    assert [clip.source_track_id for clip in fuzzy] == ["/music/4190"]
    assert not is_auto_match(
        track,
        TrackRef(platform="gequbao", external_id="4190", title="Whiplash", artist="aespa"),
    )

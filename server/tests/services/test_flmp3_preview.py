from __future__ import annotations

from urllib.parse import quote

import httpx
import pytest
from app.domain.models import TrackRef
from app.fallback.flmp3 import Flmp3Preview, _song_hits, _validated_playback_url

BASE_URL = "https://music.example"
SEARCH_HTML = """
<ul class="flex flex-wrap">
  <li>
    <a href="/song/126241.html">
      <div class="pic"></div>
      <div class="con">
        <div class="t">
          <h3>稻香</h3>
          <p>大宥</p>
        </div>
      </div>
    </a>
  </li>
  <li>
    <a href="/song/46.html">
      <div class="pic"></div>
      <div class="con">
        <div class="t">
          <h3>稻香</h3>
          <p>周杰伦</p>
        </div>
      </div>
    </a>
  </li>
</ul>
"""
PLAY_URL = "https://car-lv.kuwo.cn/token/resource/30106/trackmedia/M500003aAYrm3GE0Ac.mp3"


async def _offline_guard(_url: str, _hosts: object) -> None:
    return None


def _track() -> TrackRef:
    return TrackRef(platform="qqmusic", external_id="q1", title="稻香", artist="周杰伦")


def test_search_parser_reads_title_and_artist() -> None:
    hits = _song_hits(SEARCH_HTML)
    assert [(hit.song_id, hit.title, hit.artist) for hit in hits] == [
        ("126241", "稻香", "大宥"),
        ("46", "稻香", "周杰伦"),
    ]


def test_playurl_rejects_an_off_allowlist_host() -> None:
    assert (
        _validated_playback_url(PLAY_URL, ("kuwo.cn",))
        == "https://car-lv.kuwo.cn/token/resource/30106/trackmedia/M500003aAYrm3GE0Ac.mp3"
    )
    assert _validated_playback_url("https://evil.example/x.mp3", ("kuwo.cn",)) is None
    assert _validated_playback_url("http://car-lv.kuwo.cn/x.mp3", ("kuwo.cn",)) is None


@pytest.mark.asyncio
async def test_preview_skips_a_cover_and_uses_playurl() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/search.html":
            return httpx.Response(200, text=SEARCH_HTML)
        if request.url.path == "/api/playurl.php":
            assert request.url.params.get("id") == "46"
            assert str(request.headers.get("referer")).endswith("/song/46.html")
            return httpx.Response(200, text=PLAY_URL)
        return httpx.Response(404, text="missing")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = Flmp3Preview(client, BASE_URL, url_guard=_offline_guard)
        clips = [clip async for clip in source.iter_preview_clips(_track())]

    assert [clip.source_track_id for clip in clips] == ["/song/46.html"]
    assert clips[0].url == PLAY_URL
    assert clips[0].media_type == "audio/mpeg"
    assert any("/search.html" in url for url in seen)
    assert f"{BASE_URL}/search.html?keyword={quote('稻香 周杰伦', safe='')}" in seen

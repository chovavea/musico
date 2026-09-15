from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from app.domain.models import PreviewInfo, TrackRef

# Kuwo's anonymous play-address endpoint, the one its own web player calls. It
# answers JSON holding a signed CDN URL on a *.kuwo.cn host.
_PLAY_URL = "https://antiserver.kuwo.cn/anti.s"
_PARAMS: dict[str, Any] = {
    "type": "convert_url3",
    "format": "mp3",
    "response": "url",
    # 128 kbps is the one bitrate Kuwo hands out for every track it streams
    # anonymously; a 320 kbps request answers with the placeholder file below
    # whenever the track has no 320 kbps copy, so the preview stays low tier.
    "br": "128kmp3",
}
_HEADERS = {"Referer": "https://www.kuwo.cn/"}
_RID_PREFIX = "MUSIC_"
# Kuwo reports success for every id, including tracks it will not stream to an
# anonymous listener (unknown ids, paid tracks, blocked regions): all of them
# resolve to this single tiny 11-second file. Anything else is real audio.
_UNAVAILABLE_FILE = "588957081.mp3"


class KuwoPreview:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def preview(self, track: TrackRef) -> PreviewInfo:
        response = await self._client.get(
            _PLAY_URL,
            params={**_PARAMS, "rid": f"{_RID_PREFIX}{track.external_id}"},
            headers=_HEADERS,
        )
        response.raise_for_status()
        return parse_preview_payload(response.json())


def parse_preview_payload(payload: Any) -> PreviewInfo:
    """Read the anonymous play address, or nothing when Kuwo has no audio."""
    if not isinstance(payload, dict) or payload.get("code") != 200:
        return PreviewInfo(preview_url=None, quality=None)
    url = payload.get("url")
    if not isinstance(url, str) or not url:
        return PreviewInfo(preview_url=None, quality=None)
    if _is_unavailable(url):
        return PreviewInfo(preview_url=None, quality=None)
    return PreviewInfo(preview_url=url, quality="low")


def _is_unavailable(url: str) -> bool:
    # Signed CDN URLs may carry a query or a trailing slash; only the path
    # filename identifies the shared 11-second placeholder.
    name = unquote(urlparse(url).path).rstrip("/").rsplit("/", 1)[-1]
    return name.lower() == _UNAVAILABLE_FILE


def create_preview(client: httpx.AsyncClient) -> KuwoPreview:
    return KuwoPreview(client)

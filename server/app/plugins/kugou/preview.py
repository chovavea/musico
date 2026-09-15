from __future__ import annotations

from typing import Any, Literal

import httpx

from app.domain.models import PreviewInfo, TrackRef

_PLAY_URL = "https://m.kugou.com/app/i/getSongInfo.php"
_PARAMS: dict[str, Any] = {"cmd": "playInfo", "from": "mkugou", "version": "9108"}
_HEADERS = {"Referer": "https://www.kugou.com/"}
_MEDIUM_BITRATE = 320


class KugouPreview:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def preview(self, track: TrackRef) -> PreviewInfo:
        response = await self._client.get(
            _PLAY_URL,
            params={**_PARAMS, "hash": track.external_id},
            headers=_HEADERS,
        )
        response.raise_for_status()
        return parse_preview_payload(response.json())


def parse_preview_payload(payload: Any) -> PreviewInfo:
    """Read the anonymous play URL, or nothing when the track needs a purchase.

    Kugou answers member-only tracks with `status: 0` / `"需要付费"` and no URL
    at all, and publishes no audition clip for them, so the caller is left to
    fall back to another platform instead of pretending there is audio.
    """
    if not isinstance(payload, dict) or payload.get("status") != 1:
        return PreviewInfo(preview_url=None, quality=None)
    url = payload.get("url")
    if not isinstance(url, str) or not url:
        url = _first_backup_url(payload.get("backup_url"))
    if not url:
        return PreviewInfo(preview_url=None, quality=None)
    return PreviewInfo(preview_url=url, quality=_quality(payload.get("bitRate")))


def _first_backup_url(value: object) -> str:
    if not isinstance(value, list):
        return ""
    for item in value:
        if isinstance(item, str) and item:
            return item
    return ""


def _quality(bit_rate: object) -> Literal["low", "medium"]:
    if isinstance(bit_rate, int) and not isinstance(bit_rate, bool) and bit_rate >= _MEDIUM_BITRATE:
        return "medium"
    return "low"


def create_preview(client: httpx.AsyncClient) -> KugouPreview:
    return KugouPreview(client)

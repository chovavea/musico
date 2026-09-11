from __future__ import annotations

from typing import Any

import httpx

from app.domain.models import PreviewInfo, TrackRef

_DETAIL_URL = "https://api.bilibili.com/x/copyright-music-publicity/bgm/detail"
_PLAY_URL = "https://api.bilibili.com/x/player/playurl"
_HEADERS = {
    "Referer": "https://music.bilibili.com/pc/rank",
    "User-Agent": "Mozilla/5.0",
}


class BilibiliPreview:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def preview(self, track: TrackRef) -> PreviewInfo:
        detail_response = await self._client.get(
            _DETAIL_URL,
            params={"music_id": track.external_id},
            headers=_HEADERS,
        )
        detail_response.raise_for_status()
        detail = parse_detail_payload(detail_response.json())
        if detail is None:
            return PreviewInfo(preview_url=None, quality=None)
        aid, cid, bvid = detail

        response = await self._client.get(
            _PLAY_URL,
            params={
                "avid": aid,
                "cid": cid,
                "qn": 16,
                "fnver": 0,
                "fnval": 0,
                "fourk": 0,
            },
            headers={
                **_HEADERS,
                "Referer": (
                    f"https://www.bilibili.com/video/{bvid}"
                    if bvid
                    else _HEADERS["Referer"]
                ),
            },
        )
        response.raise_for_status()
        preview_url = parse_preview_payload(response.json())
        return PreviewInfo(
            preview_url=preview_url,
            quality="low" if preview_url else None,
        )


def parse_detail_payload(payload: Any) -> tuple[int, int, str] | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("support_listen") is not True:
        return None
    aid = _positive_int(data.get("mv_aid"))
    cid = _positive_int(data.get("mv_cid"))
    bvid = data.get("mv_bvid")
    if aid is None or cid is None:
        return None
    return aid, cid, bvid if isinstance(bvid, str) else ""


def parse_preview_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    durl = data.get("durl")
    if not isinstance(durl, list):
        return None
    for item in durl:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
    return None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        try:
            number = int(value)
        except ValueError:
            return None
    else:
        return None
    return number if number > 0 else None


def create_preview(client: httpx.AsyncClient) -> BilibiliPreview:
    return BilibiliPreview(client)

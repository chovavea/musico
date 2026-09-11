from __future__ import annotations

from typing import Any, Literal

import httpx

from app.domain.models import PreviewInfo, TrackRef

_MUSICU_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
_GUID = "10000"
_UIN = "0"
_HEADERS = {
    "Origin": "https://y.qq.com",
    "Referer": "https://y.qq.com",
}

# Anonymous GetVkey: M500 first, C400 as trial fallback. No cookie.
_FORMATS: tuple[tuple[str, str, Literal["low", "medium"]], ...] = (
    ("M500", ".mp3", "medium"),
    ("C400", ".m4a", "low"),
)


class QQMusicPreview:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def preview(self, track: TrackRef) -> PreviewInfo:
        for prefix, suffix, quality in _FORMATS:
            response = await self._client.post(
                _MUSICU_URL,
                json=vkey_payload(track.external_id, vkey_filename(track.external_id, prefix, suffix)),
                headers=_HEADERS,
            )
            response.raise_for_status()
            url = parse_qq_preview_url(response.json())
            if url:
                return PreviewInfo(preview_url=url, quality=quality)
        return PreviewInfo(preview_url=None, quality=None)


def vkey_filename(songmid: str, prefix: str, suffix: str) -> str:
    return f"{prefix}{songmid}{songmid}{suffix}"


def vkey_payload(songmid: str, filename: str) -> dict[str, Any]:
    return {
        "req_1": {
            "module": "vkey.GetVkeyServer",
            "method": "CgiGetVkey",
            "param": {
                "filename": [filename],
                "guid": _GUID,
                "songmid": [songmid],
                "songtype": [0],
                "uin": _UIN,
                "loginflag": 1,
                "platform": "20",
            },
        },
        "loginUin": _UIN,
        "comm": {
            "uin": _UIN,
            "format": "json",
            "ct": 24,
            "cv": 0,
        },
    }


def parse_qq_preview_url(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    req = payload.get("req_1") or payload.get("req_0")
    data = req.get("data") if isinstance(req, dict) else None
    if not isinstance(data, dict):
        return None
    infos = data.get("midurlinfo")
    if not isinstance(infos, list) or not infos:
        return None
    info = infos[0]
    if not isinstance(info, dict):
        return None
    purl = info.get("purl")
    if not isinstance(purl, str) or not purl:
        return None
    if purl.startswith("http://") or purl.startswith("https://"):
        return purl
    sip = _pick_sip(data.get("sip"))
    if not sip:
        return None
    return f"{sip}{purl}"


def _pick_sip(sips: object) -> str:
    if not isinstance(sips, list):
        return ""
    candidates = [item for item in sips if isinstance(item, str) and item]
    if not candidates:
        return ""
    return next((item for item in candidates if not item.startswith("http://ws")), candidates[0])


def create_preview(client: httpx.AsyncClient) -> QQMusicPreview:
    return QQMusicPreview(client)

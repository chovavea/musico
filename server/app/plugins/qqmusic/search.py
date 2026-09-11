from __future__ import annotations

from typing import Any

import httpx

from app.domain.models import TrackQuery, TrackRef

_SEARCH_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
_HEADERS = {"Origin": "https://y.qq.com", "Referer": "https://y.qq.com/"}
_COVER_CDN = "https://y.gtimg.cn/music/photo_new"
# ct/cv are sent by the y.qq.com web client; older values make the API answer
# with an empty song list for the same query.
_COMM = {"ct": "19", "cv": "1859", "uin": "0", "format": "json"}


class QQMusicSearch:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: TrackQuery) -> list[TrackRef]:
        keyword = f"{query.title} {query.artist}".strip()
        if not keyword:
            return []
        response = await self._client.post(
            _SEARCH_URL,
            json=search_payload(keyword, query.limit),
            headers=_HEADERS,
        )
        response.raise_for_status()
        return parse_search_payload(response.json(), limit=query.limit)


def search_payload(keyword: str, limit: int) -> dict[str, Any]:
    return {
        "comm": dict(_COMM),
        "req_1": {
            "module": "music.search.SearchCgiService",
            "method": "DoSearchForQQMusicDesktop",
            "param": {
                "query": keyword,
                "num_per_page": limit,
                "page_num": 1,
                "search_type": 0,
                "grp": 1,
            },
        },
    }


def parse_search_payload(payload: Any, *, limit: int) -> list[TrackRef]:
    req = payload.get("req_1") if isinstance(payload, dict) else None
    data = req.get("data") if isinstance(req, dict) else None
    body = data.get("body") if isinstance(data, dict) else None
    song = body.get("song") if isinstance(body, dict) else None
    items = song.get("list") if isinstance(song, dict) else None
    if not isinstance(items, list):
        return []
    tracks: list[TrackRef] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        songmid = raw.get("mid")
        title = raw.get("name") or raw.get("title")
        if not songmid or not title:
            continue
        tracks.append(
            TrackRef(
                platform="qqmusic",
                external_id=str(songmid),
                title=str(title),
                artist=_artist(raw),
                album=_album(raw),
                duration_ms=_duration_ms(raw),
                isrc=_isrc(raw),
                version=_version(raw),
                cover_url=_cover_url(raw),
                official_url=f"https://y.qq.com/n/ryqq/songDetail/{songmid}",
            )
        )
        if len(tracks) >= limit:
            break
    return tracks


def _artist(raw: dict[str, Any]) -> str:
    singers = raw.get("singer") or []
    if not isinstance(singers, list):
        return "未知"
    names = [
        str(item.get("name")) for item in singers if isinstance(item, dict) and item.get("name")
    ]
    return " / ".join(names) or "未知"


def _album(raw: dict[str, Any]) -> str | None:
    album = raw.get("album")
    name = album.get("name") if isinstance(album, dict) else None
    return str(name) if name else None


def _cover_url(raw: dict[str, Any]) -> str | None:
    album = raw.get("album")
    if not isinstance(album, dict):
        return None
    direct = album.get("picUrl")
    if direct:
        return str(direct)
    album_mid = album.get("mid")
    if album_mid:
        return f"{_COVER_CDN}/T002R300x300M000{album_mid}.jpg"
    return None


def _isrc(raw: dict[str, Any]) -> str | None:
    for field in ("isrc", "isrc_code", "isrcCode"):
        value = raw.get(field)
        if value:
            return str(value)
    return None


def _version(raw: dict[str, Any]) -> str | None:
    value = raw.get("version") or raw.get("subtitle")
    return str(value) if value else None


def _duration_ms(raw: dict[str, Any]) -> int | None:
    interval = raw.get("interval")
    if isinstance(interval, int) and interval > 0:
        return interval * 1000
    return None


def create_search(client: httpx.AsyncClient) -> QQMusicSearch:
    return QQMusicSearch(client)

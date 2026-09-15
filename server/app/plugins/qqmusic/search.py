from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.domain.models import TrackQuery, TrackRef

_SEARCH_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
_HEADERS = {"Origin": "https://y.qq.com", "Referer": "https://y.qq.com/"}
_COVER_CDN = "https://y.gtimg.cn/music/photo_new"
# ct/cv are sent by the y.qq.com web client; older values make the API answer
# with an empty song list for the same query.
_COMM = {"ct": "19", "cv": "1859", "uin": "0", "format": "json"}
# DoSearchForQQMusicDesktop silently answers with an empty song list once
# num_per_page passes 60 (verified for 61..100), which is why a 100-item search
# used to come back empty; larger limits are paged instead.
_MAX_PAGE_SIZE = 60


class QQMusicSearch:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: TrackQuery) -> list[TrackRef]:
        keyword = f"{query.title} {query.artist}".strip()
        if not keyword:
            return []
        page_size = min(query.limit, _MAX_PAGE_SIZE)
        # Pages do not depend on each other, so they are requested together: one
        # round trip instead of one per page.
        payloads = await asyncio.gather(
            *(
                self._request(keyword, query.limit, page)
                for page in range(1, -(-query.limit // page_size) + 1)
            ),
            return_exceptions=True,
        )
        return _tracks_from_pages(payloads, limit=query.limit, page_size=page_size)

    async def _request(self, keyword: str, limit: int, page: int) -> Any:
        response = await self._client.post(
            _SEARCH_URL,
            json=search_payload(keyword, limit, page=page),
            headers=_HEADERS,
        )
        response.raise_for_status()
        payload = response.json()
        _check_status(payload)
        return payload


def _tracks_from_pages(payloads: list[Any], *, limit: int, page_size: int) -> list[TrackRef]:
    """Keep successful pages when a later page is throttled or cancelled."""
    errors: list[BaseException] = []
    tracks: list[TrackRef] = []
    seen: set[str] = set()
    saw_success = False
    for payload in payloads:
        if isinstance(payload, BaseException):
            errors.append(payload)
            continue
        saw_success = True
        found = parse_search_payload(payload, limit=limit - len(tracks))
        added = 0
        for track in found:
            if track.external_id in seen:
                continue
            seen.add(track.external_id)
            tracks.append(track)
            added += 1
        # A short page means the result set is exhausted, so the pages behind
        # it must not be appended; a page with nothing new means the API
        # repeated itself and the rest is worthless.
        if added == 0 or len(found) < page_size:
            break
    if not saw_success and errors:
        raise errors[0]
    return tracks


def _check_status(payload: Any) -> None:
    """Reject a throttled response instead of reporting it as no matches.
    The API answers HTTP 200 with ``req_1.code = 2001`` and an empty song list
    while it throttles a client; a genuine miss is ``code = 0`` with an empty
    list. Treating the two the same hid the throttling behind an "empty"
    platform status.
    """
    req = payload.get("req_1") if isinstance(payload, dict) else None
    code = req.get("code") if isinstance(req, dict) else None
    if isinstance(code, int) and code != 0:
        raise ValueError(f"qqmusic search rejected the request: code={code}")


def search_payload(keyword: str, limit: int, *, page: int = 1) -> dict[str, Any]:
    return {
        "comm": dict(_COMM),
        "req_1": {
            "module": "music.search.SearchCgiService",
            "method": "DoSearchForQQMusicDesktop",
            "param": {
                "query": keyword,
                "num_per_page": min(limit, _MAX_PAGE_SIZE),
                "page_num": page,
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

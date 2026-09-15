from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.domain.models import TrackQuery, TrackRef

# Same HTTPS reason as the chart plugin: mobilecdn.kugou.com only speaks plain
# HTTP, while mobiles.kugou.com serves the identical v3 API with a valid
# certificate.
_SEARCH_URL = "https://mobiles.kugou.com/api/v3/search/song"
_HEADERS = {"Referer": "https://www.kugou.com/"}
_FIXED_PARAMS: dict[str, Any] = {"format": "json", "page": 1, "showtype": 1, "plat": 0, "sver": 5}
# The v3 endpoint ignores pagesize above 30 and answers with 30 rows, so a
# larger limit has to be paged instead of asked for in one request.
_MAX_PAGE_SIZE = 30


class KugouSearch:
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
        response = await self._client.get(
            _SEARCH_URL,
            params=search_params(keyword, limit, page=page),
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
    """Reject a response the API marked as failed instead of reporting no matches.
    A successful search always carries ``status = 1`` and ``errcode = 0``; both
    an empty result set and a full one use it. Anything else (throttling, an
    invalid request) must surface as a failed platform, not as "no results".
    """
    if not isinstance(payload, dict):
        return
    status = payload.get("status")
    errcode = payload.get("errcode")
    if (isinstance(status, int) and status != 1) or (
        isinstance(errcode, int) and errcode != 0
    ):
        raise ValueError(f"kugou search rejected the request: status={status} errcode={errcode}")


def search_params(keyword: str, limit: int, *, page: int = 1) -> dict[str, Any]:
    return {
        **_FIXED_PARAMS,
        "keyword": keyword,
        "pagesize": min(limit, _MAX_PAGE_SIZE),
        "page": page,
    }


def parse_search_payload(payload: Any, *, limit: int) -> list[TrackRef]:
    data = payload.get("data") if isinstance(payload, dict) else None
    songs = data.get("info") if isinstance(data, dict) else None
    if not isinstance(songs, list):
        return []
    tracks: list[TrackRef] = []
    for raw in songs:
        if not isinstance(raw, dict):
            continue
        song_hash = raw.get("hash")
        title = raw.get("songname")
        if not song_hash or not title:
            continue
        tracks.append(
            TrackRef(
                platform="kugou",
                external_id=str(song_hash).lower(),
                title=str(title),
                artist=_artist(raw),
                album=_album(raw),
                duration_ms=_duration_ms(raw),
                version=_version(raw),
                cover_url=_cover_url(raw),
                official_url=_official_url(song_hash, raw.get("album_id")),
            )
        )
        if len(tracks) >= limit:
            break
    return tracks


def _artist(raw: dict[str, Any]) -> str:
    value = raw.get("singername")
    return str(value) if value else "未知"


def _album(raw: dict[str, Any]) -> str | None:
    value = raw.get("album_name")
    return str(value) if value else None


def _cover_url(raw: dict[str, Any]) -> str | None:
    trans = raw.get("trans_param")
    if isinstance(trans, dict) and trans.get("union_cover"):
        return str(trans["union_cover"])
    return None


def _version(raw: dict[str, Any]) -> str | None:
    value = raw.get("othername") or raw.get("othername_original")
    return str(value) if value else None


def _duration_ms(raw: dict[str, Any]) -> int | None:
    seconds = raw.get("duration")
    if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds > 0:
        return seconds * 1000
    return None


def _official_url(song_hash: object, album_id: object) -> str:
    url = f"https://www.kugou.com/song/#hash={str(song_hash).lower()}"
    return f"{url}&album_id={album_id}" if album_id else url


def create_search(client: httpx.AsyncClient) -> KugouSearch:
    return KugouSearch(client)

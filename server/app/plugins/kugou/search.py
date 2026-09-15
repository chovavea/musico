from __future__ import annotations

from typing import Any

import httpx

from app.domain.models import TrackQuery, TrackRef

# Same HTTPS reason as the chart plugin: mobilecdn.kugou.com only speaks plain
# HTTP, while mobiles.kugou.com serves the identical v3 API with a valid
# certificate.
_SEARCH_URL = "https://mobiles.kugou.com/api/v3/search/song"
_HEADERS = {"Referer": "https://www.kugou.com/"}
_FIXED_PARAMS: dict[str, Any] = {"format": "json", "page": 1, "showtype": 1, "plat": 0, "sver": 5}


class KugouSearch:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: TrackQuery) -> list[TrackRef]:
        keyword = f"{query.title} {query.artist}".strip()
        if not keyword:
            return []
        response = await self._client.get(
            _SEARCH_URL,
            params={**_FIXED_PARAMS, "keyword": keyword, "pagesize": query.limit},
            headers=_HEADERS,
        )
        response.raise_for_status()
        return parse_search_payload(response.json(), limit=query.limit)


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

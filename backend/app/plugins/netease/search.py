from __future__ import annotations

from typing import Any

import httpx

from app.domain.models import TrackQuery, TrackRef

_SEARCH_URL = "https://music.163.com/api/search/get"
_HEADERS = {"Referer": "https://music.163.com/"}


class NeteaseSearch:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: TrackQuery) -> list[TrackRef]:
        keyword = f"{query.title} {query.artist}".strip()
        if not keyword:
            return []
        response = await self._client.get(
            _SEARCH_URL,
            params={"s": keyword, "type": 1, "limit": query.limit, "offset": 0},
            headers=_HEADERS,
        )
        response.raise_for_status()
        return parse_search_payload(response.json(), limit=query.limit)


def parse_search_payload(payload: Any, *, limit: int) -> list[TrackRef]:
    result = payload.get("result") if isinstance(payload, dict) else None
    songs = result.get("songs") if isinstance(result, dict) else None
    if not isinstance(songs, list):
        return []
    tracks: list[TrackRef] = []
    for raw in songs:
        if not isinstance(raw, dict):
            continue
        song_id = raw.get("id")
        title = raw.get("name")
        if song_id is None or not title:
            continue
        tracks.append(
            TrackRef(
                platform="netease",
                external_id=str(song_id),
                title=str(title),
                artist=_artist(raw),
                album=_album(raw),
                duration_ms=_duration_ms(raw),
            )
        )
        if len(tracks) >= limit:
            break
    return tracks


def _artist(raw: dict[str, Any]) -> str:
    artists = raw.get("artists") or raw.get("ar") or []
    if not isinstance(artists, list):
        return "未知"
    names = [
        str(item.get("name")) for item in artists if isinstance(item, dict) and item.get("name")
    ]
    return " / ".join(names) or "未知"


def _album(raw: dict[str, Any]) -> str | None:
    album = raw.get("album") or raw.get("al")
    name = album.get("name") if isinstance(album, dict) else None
    return str(name) if name else None


def _duration_ms(raw: dict[str, Any]) -> int | None:
    for field in ("duration", "dt"):
        value = raw.get(field)
        if isinstance(value, int) and value > 0:
            return value
    return None


def create_search(client: httpx.AsyncClient) -> NeteaseSearch:
    return NeteaseSearch(client)

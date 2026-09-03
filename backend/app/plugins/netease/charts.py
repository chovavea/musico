from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.domain.models import BoardSpec, RawRankItem

log = structlog.get_logger(__name__)

_PLAYLIST_URL = "https://music.163.com/api/v6/playlist/detail"


class NeteaseCharts:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_board(self, board_config: BoardSpec) -> list[RawRankItem]:
        playlist_id = board_config.extra.get("playlist_id")
        if not isinstance(playlist_id, str) or not playlist_id:
            raise ValueError("netease extra.playlist_id must be a non-empty string")
        response = await self._client.get(
            _PLAYLIST_URL,
            params={"id": playlist_id, "n": 100},
            headers={"Referer": "https://music.163.com/"},
        )
        response.raise_for_status()
        payload: Any = response.json()
        playlist = payload.get("playlist") if isinstance(payload, dict) else None
        tracks = playlist.get("tracks") if isinstance(playlist, dict) else None
        if not isinstance(tracks, list):
            raise ValueError("netease playlist payload missing tracks")
        items: list[RawRankItem] = []
        for index, raw in enumerate(tracks, start=1):
            parsed = _parse_item(raw, index)
            if parsed is None:
                log.warning("netease_skip_item", board_id=board_config.id, index=index)
                continue
            items.append(parsed)
        return items

    async def list_catalog(self) -> list[dict[str, Any]]:
        response = await self._client.get(
            "https://music.163.com/api/toplist",
            headers={"Referer": "https://music.163.com/"},
        )
        response.raise_for_status()
        payload: Any = response.json()
        lists = payload.get("list") if isinstance(payload, dict) else None
        if not isinstance(lists, list):
            raise ValueError("netease catalog payload missing list")
        buckets: dict[str, list[dict[str, Any]]] = {
            "官方榜": [],
            "曲风语种": [],
            "全球转载": [],
            "其他": [],
        }
        for chart in lists:
            if not isinstance(chart, dict) or chart.get("id") is None or not chart.get("name"):
                continue
            item = {"key": str(chart["id"]), "name": str(chart["name"]), "playable": True}
            buckets[_netease_bucket(int(chart["id"]))].append(item)
        return [{"name": name, "charts": charts} for name, charts in buckets.items() if charts]


_NETEASE_CORE = {
    19723756,
    3779629,
    2884035,
    3778678,
    18176153161,
    13372522766,
    5338990334,
    6688069460,
    6723173524,
    7775163417,
    8246775932,
}
_NETEASE_WORLD = {180106, 60198, 3812895, 21845217, 60131, 27135204, 6939992364}
_NETEASE_GENRE = {
    71384707,
    1978921795,
    991319590,
    14028249541,
    71385702,
    745956260,
    2809513713,
    2809577409,
    3001835560,
    3001795926,
    3001890046,
    5059644681,
    5059633707,
    5059642708,
    5059661515,
    6732051320,
    6732014811,
    6886768100,
    7095271308,
    7356827205,
    12225155968,
}


def _netease_bucket(playlist_id: int) -> str:
    if playlist_id in _NETEASE_CORE:
        return "官方榜"
    if playlist_id in _NETEASE_GENRE:
        return "曲风语种"
    if playlist_id in _NETEASE_WORLD:
        return "全球转载"
    return "其他"


def _parse_item(raw: object, rank: int) -> RawRankItem | None:
    if not isinstance(raw, dict):
        return None
    song_id = raw.get("id")
    title = raw.get("name")
    if song_id is None or not title:
        return None
    artists = raw.get("ar") or raw.get("artists") or []
    if isinstance(artists, list):
        artist = " / ".join(
            str(item.get("name")) for item in artists if isinstance(item, dict) and item.get("name")
        )
    else:
        artist = "未知"
    if not artist:
        artist = "未知"
    album = raw.get("al") or raw.get("album") or {}
    cover = album.get("picUrl") if isinstance(album, dict) else None
    return RawRankItem(
        rank=rank,
        external_id=str(song_id),
        title=str(title),
        artist=artist,
        cover_url=str(cover) if cover else None,
        official_url=f"https://music.163.com/song?id={song_id}",
    )


def create_chart(client: httpx.AsyncClient) -> NeteaseCharts:
    return NeteaseCharts(client)

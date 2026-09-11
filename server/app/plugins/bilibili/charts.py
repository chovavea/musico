from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.domain.models import BoardSpec, RawRankItem

log = structlog.get_logger(__name__)

_API_BASE = "https://api.bilibili.com/x/copyright-music-publicity/toplist"
_PERIODS_URL = f"{_API_BASE}/all_period"
_MUSIC_LIST_URL = f"{_API_BASE}/music_list"
_HEADERS = {
    "Referer": "https://music.bilibili.com/pc/rank",
    "User-Agent": "Mozilla/5.0",
}

_LIST_TYPES = {
    1: "热歌榜",
    3: "二创榜",
}


class BilibiliCharts:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_board(self, board_config: BoardSpec) -> list[RawRankItem]:
        list_type = _list_type(board_config.extra.get("list_type"))
        if list_type is None:
            raise ValueError("bilibili extra.list_type must be 1 or 3")
        period_id = await self._latest_period_id(list_type)
        response = await self._client.get(
            _MUSIC_LIST_URL,
            params={"list_id": period_id},
            headers=_HEADERS,
        )
        response.raise_for_status()
        payload: Any = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        songs = data.get("list") if isinstance(data, dict) else None
        if not isinstance(songs, list):
            raise ValueError("bilibili music toplist payload missing list")

        items: list[RawRankItem] = []
        for index, raw in enumerate(songs, start=1):
            parsed = _parse_item(raw, index)
            if parsed is None:
                log.warning("bilibili_skip_item", board_id=board_config.id, index=index)
                continue
            items.append(parsed)
        return items

    async def _latest_period_id(self, list_type: int) -> int:
        response = await self._client.get(
            _PERIODS_URL,
            params={"list_type": list_type},
            headers=_HEADERS,
        )
        response.raise_for_status()
        payload: Any = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        periods_by_year = data.get("list") if isinstance(data, dict) else None
        if not isinstance(periods_by_year, dict):
            raise ValueError("bilibili music periods payload missing list")

        periods: list[dict[str, Any]] = []
        for periods_in_year in periods_by_year.values():
            if not isinstance(periods_in_year, list):
                continue
            periods.extend(item for item in periods_in_year if isinstance(item, dict))
        if not periods:
            raise ValueError("bilibili music periods payload has no periods")
        latest = max(periods, key=lambda item: _number(item.get("publish_time")))
        period_id = _positive_int(latest.get("ID"))
        if period_id is None:
            raise ValueError("bilibili music periods payload missing latest ID")
        return period_id

    async def list_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "哔哩哔哩音乐榜单",
                "charts": [
                    {
                        "key": str(list_type),
                        "name": name,
                        "playable": True,
                    }
                    for list_type, name in _LIST_TYPES.items()
                ],
            }
        ]


def _parse_item(raw: object, rank: int) -> RawRankItem | None:
    if not isinstance(raw, dict):
        return None
    music_id = raw.get("music_id")
    title = raw.get("music_title")
    singer = raw.get("singer")
    if (
        not isinstance(music_id, str)
        or not music_id.strip()
        or not isinstance(title, str)
        or not title.strip()
        or not isinstance(singer, str)
        or not singer.strip()
    ):
        return None
    music_id = music_id.strip()
    raw_rank = _positive_int(raw.get("rank"))
    cover = raw.get("mv_cover") or raw.get("creation_cover")
    cover_url = str(cover) if isinstance(cover, str) and cover else None
    return RawRankItem(
        rank=raw_rank or rank,
        external_id=music_id,
        title=title.strip(),
        artist=singer.strip(),
        album=_optional_text(raw.get("album")),
        duration_ms=_duration_ms(raw.get("creation_duration")),
        cover_url=cover_url,
        official_url=f"https://music.bilibili.com/pc/music-detail?music_id={music_id}",
        raw_score=_positive_float(raw.get("heat")),
    )


def _list_type(value: object) -> int | None:
    list_type = _positive_int(value)
    return list_type if list_type in _LIST_TYPES else None


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


def _number(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _positive_float(value: object) -> float | None:
    number = _number(value)
    return number if number > 0 else None


def _duration_ms(value: object) -> int | None:
    seconds = _number(value)
    return round(seconds * 1000) if seconds > 0 else None


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def create_chart(client: httpx.AsyncClient) -> BilibiliCharts:
    return BilibiliCharts(client)

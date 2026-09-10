from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.domain.models import BoardSpec, RawRankItem

log = structlog.get_logger(__name__)

_TOPLIST_URL = "https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg"
_DETAIL_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
_COVER_CDN = "https://y.gtimg.cn/music/photo_new"


class QQMusicCharts:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_board(self, board_config: BoardSpec) -> list[RawRankItem]:
        top_id = board_config.extra.get("top_id")
        if not isinstance(top_id, int):
            raise ValueError("qqmusic extra.top_id must be an int")
        response = await self._client.get(
            _TOPLIST_URL,
            params={
                "topid": top_id,
                "format": "json",
                "inCharset": "utf-8",
                "outCharset": "utf-8",
                "notice": 0,
                "platform": "yqq",
                "needNewCode": 0,
                "tpl": 3,
                "page": "detail",
                "type": "top",
                "song_begin": 0,
                "song_num": 100,
            },
            headers={"Referer": "https://y.qq.com"},
        )
        response.raise_for_status()
        payload: Any = response.json()
        songlist = payload.get("songlist") if isinstance(payload, dict) else None
        if not isinstance(songlist, list):
            raise ValueError("qqmusic toplist payload missing songlist")
        single_covers: dict[str, str] = {}
        try:
            single_covers = await self._fetch_single_covers(top_id)
        except Exception:
            log.debug("qqmusic_single_cover_lookup_failed", board_id=board_config.id)
        items: list[RawRankItem] = []
        for index, raw in enumerate(songlist, start=1):
            parsed = _parse_item(raw, index, single_covers)
            if parsed is None:
                log.warning("qqmusic_skip_item", board_id=board_config.id, index=index)
                continue
            items.append(parsed)
        return items

    async def _fetch_single_covers(self, top_id: int) -> dict[str, str]:
        """查询官方 GetDetail，把每首歌的单曲封面（vs[1]）映射为封面 URL。"""
        payload = {
            "comm": {"ct": 24, "cv": 0},
            "req": {
                "module": "musicToplist.ToplistInfoServer",
                "method": "GetDetail",
                "param": {"topId": top_id, "offset": 0, "num": 100, "period": ""},
            },
        }
        response = await self._client.post(
            _DETAIL_URL,
            json=payload,
            headers={"Referer": "https://y.qq.com"},
        )
        response.raise_for_status()
        body: Any = response.json()
        req = body.get("req") if isinstance(body, dict) else None
        data = req.get("data") if isinstance(req, dict) else None
        song_list = data.get("songInfoList") if isinstance(data, dict) else None
        if not isinstance(song_list, list):
            return {}
        covers: dict[str, str] = {}
        for track in song_list:
            if not isinstance(track, dict):
                continue
            songmid = track.get("mid")
            vs = track.get("vs")
            if not isinstance(songmid, str) or not isinstance(vs, list) or len(vs) < 2:
                continue
            cover_mid = vs[1]
            if not isinstance(cover_mid, str) or not cover_mid:
                continue
            covers[songmid] = f"{_COVER_CDN}/T062R300x300M000{cover_mid}.jpg"
        return covers

    async def list_catalog(self) -> list[dict[str, Any]]:
        payload = {
            "comm": {"ct": 24, "cv": 0},
            "req": {
                "module": "musicToplist.ToplistInfoServer",
                "method": "GetAll",
                "param": {},
            },
        }
        response = await self._client.post(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            json=payload,
            headers={"Referer": "https://y.qq.com"},
        )
        response.raise_for_status()
        body: Any = response.json()
        req = body.get("req") if isinstance(body, dict) else None
        data = req.get("data") if isinstance(req, dict) else None
        groups = data.get("group") if isinstance(data, dict) else None
        if not isinstance(groups, list):
            raise ValueError("qqmusic catalog payload missing group")
        result: list[dict[str, Any]] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_title = str(group.get("groupName") or group.get("name") or "其他")
            charts: list[dict[str, Any]] = []
            for chart in group.get("toplist") or group.get("list") or []:
                if not isinstance(chart, dict):
                    continue
                top_id = chart.get("topId") or chart.get("topid") or chart.get("id")
                name = chart.get("title") or chart.get("name")
                if top_id is None or not name:
                    continue
                top_key = str(int(top_id))
                chart_name = str(name)
                if "MV" in chart_name or top_id == 201:
                    continue
                charts.append({"key": top_key, "name": chart_name, "playable": True})
            if charts:
                result.append({"name": group_title, "charts": charts})
        return result


def _parse_item(
    raw: object,
    rank: int,
    single_covers: dict[str, str] | None = None,
) -> RawRankItem | None:
    if not isinstance(raw, dict):
        return None
    data = raw.get("data")
    if not isinstance(data, dict):
        data = raw
    songmid = data.get("songmid") or data.get("mid")
    title = data.get("songname") or data.get("name")
    if not songmid or not title:
        return None
    singers = data.get("singer") or []
    if isinstance(singers, list):
        artist = " / ".join(
            str(item.get("name")) for item in singers if isinstance(item, dict) and item.get("name")
        )
    else:
        artist = str(singers)
    if not artist:
        artist = "未知"
    albummid = str(data.get("albummid") or "")
    cover: str | None = None
    if single_covers and songmid:
        cover = single_covers.get(str(songmid))
    if not cover and albummid:
        cover = f"{_COVER_CDN}/T002R300x300M000{albummid}.jpg"
    preview = data.get("preview") if isinstance(data.get("preview"), str) else None
    raw_score = _optional_float(raw.get("cur_count"))
    return RawRankItem(
        rank=rank,
        external_id=str(songmid),
        title=str(title),
        artist=artist,
        cover_url=cover,
        official_url=f"https://y.qq.com/n/ryqq/songDetail/{songmid}",
        raw_score=raw_score,
        preview_url=preview or None,
    )


def _optional_float(value: object) -> float | None:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def create_chart(client: httpx.AsyncClient) -> QQMusicCharts:
    return QQMusicCharts(client)

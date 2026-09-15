from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.domain.models import BoardSpec, RawRankItem

log = structlog.get_logger(__name__)

# The v3 API is also served by mobilecdn.kugou.com, but that host only speaks
# plain HTTP: its TLS certificate does not match the name. mobiles.kugou.com is
# the same service behind a valid certificate, so every call stays on HTTPS.
_RANK_LIST_URL = "https://mobiles.kugou.com/api/v3/rank/list"
_RANK_SONG_URL = "https://mobiles.kugou.com/api/v3/rank/song"
_COMMON_PARAMS: dict[str, Any] = {"version": 9108, "plat": 0, "area_code": 1, "apiver": 6}
_PAGE_SIZE = 100
_MAX_PAGES = 10

# The `classify` values the rank list publishes, in catalog display order.
_BUCKETS: tuple[tuple[int, str], ...] = (
    (1, "热门榜"),
    (2, "地区榜"),
    (5, "曲风语种"),
    (3, "特色榜"),
    (4, "全球转载"),
)
_OTHER_BUCKET = "其他"


class KugouCharts:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_board(self, board_config: BoardSpec) -> list[RawRankItem]:
        rank_id = board_config.extra.get("rank_id")
        if not isinstance(rank_id, int) or isinstance(rank_id, bool):
            raise ValueError("kugou extra.rank_id must be an int")
        items: list[RawRankItem] = []
        seen_ids: set[str] = set()
        total: int | None = None
        for page in range(1, _MAX_PAGES + 1):
            payload = await self._fetch_rank_page(rank_id, page)
            total = _total(payload, total)
            rows = _rows(payload)
            added = 0
            for index, raw in enumerate(rows, start=1):
                fallback_rank = (page - 1) * _PAGE_SIZE + index
                parsed = _parse_item(raw, fallback_rank)
                if parsed is None:
                    log.warning(
                        "kugou_skip_item",
                        board_id=board_config.id,
                        index=fallback_rank,
                    )
                    continue
                if parsed.external_id in seen_ids:
                    continue
                seen_ids.add(parsed.external_id)
                items.append(parsed)
                added += 1
            if not rows or len(rows) < _PAGE_SIZE or added == 0:
                break
            if total is not None and page * _PAGE_SIZE >= total:
                break
        return items

    async def _fetch_rank_page(self, rank_id: int, page: int) -> Any:
        response = await self._client.get(
            _RANK_SONG_URL,
            params={
                **_COMMON_PARAMS,
                "rankid": rank_id,
                "page": page,
                "pagesize": _PAGE_SIZE,
                "with_cover": 0,
                # with_res_tag=1 wraps the JSON body in an HTML comment.
                "with_res_tag": 0,
            },
        )
        response.raise_for_status()
        return response.json()

    async def list_catalog(self) -> list[dict[str, Any]]:
        response = await self._client.get(
            _RANK_LIST_URL,
            params={
                **_COMMON_PARAMS,
                "showtype": 2,
                "parentid": 0,
                "withsong": 0,
                "cover": 0,
            },
        )
        response.raise_for_status()
        buckets: dict[str, list[dict[str, Any]]] = {name: [] for _classify, name in _BUCKETS}
        buckets[_OTHER_BUCKET] = []
        for chart in _rows(response.json()):
            if not isinstance(chart, dict):
                continue
            rank_id = chart.get("rankid")
            name = chart.get("rankname")
            # Parent entries only group child ranks; the children are the real charts.
            if rank_id is None or not name or chart.get("haschildren"):
                continue
            item = {"key": str(rank_id), "name": str(name), "playable": True}
            buckets[_bucket_name(chart.get("classify"))].append(item)
        groups = [{"name": name, "charts": buckets[name]} for _classify, name in _BUCKETS]
        groups.append({"name": _OTHER_BUCKET, "charts": buckets[_OTHER_BUCKET]})
        return [group for group in groups if group["charts"]]


def _rows(payload: Any) -> list[Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("info") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def _total(payload: Any, current: int | None) -> int | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    value = data.get("total") if isinstance(data, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return current


def _item_rank(raw: dict[str, Any], fallback: int) -> int:
    for key in ("sort", "last_sort"):
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return fallback


def _bucket_name(classify: object) -> str:
    for value, name in _BUCKETS:
        if classify == value:
            return name
    return _OTHER_BUCKET


def _parse_item(raw: object, rank: int) -> RawRankItem | None:
    if not isinstance(raw, dict):
        return None
    song_hash = raw.get("hash")
    title = raw.get("songname")
    if not song_hash or not title:
        return None
    return RawRankItem(
        rank=_item_rank(raw, rank),
        external_id=str(song_hash).lower(),
        title=str(title),
        artist=_artist(raw),
        # The rank endpoint answers with the album id and cover but never its name.
        album=None,
        duration_ms=_duration_ms(raw),
        cover_url=_cover_url(raw),
        official_url=_official_url(song_hash, raw.get("album_id")),
    )


def _artist(raw: dict[str, Any]) -> str:
    authors = raw.get("authors") or []
    if not isinstance(authors, list):
        return "未知"
    names = [
        str(item.get("author_name"))
        for item in authors
        if isinstance(item, dict) and item.get("author_name")
    ]
    return " / ".join(names) or "未知"


def _cover_url(raw: dict[str, Any]) -> str | None:
    direct = raw.get("album_sizable_cover")
    if direct:
        return str(direct)
    trans = raw.get("trans_param")
    if isinstance(trans, dict) and trans.get("union_cover"):
        return str(trans["union_cover"])
    return None


def _duration_ms(raw: dict[str, Any]) -> int | None:
    seconds = raw.get("duration")
    if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds > 0:
        return seconds * 1000
    return None


def _official_url(song_hash: object, album_id: object) -> str:
    url = f"https://www.kugou.com/song/#hash={str(song_hash).lower()}"
    return f"{url}&album_id={album_id}" if album_id else url


def create_chart(client: httpx.AsyncClient) -> KugouCharts:
    return KugouCharts(client)

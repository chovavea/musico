from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

from app.domain.models import BoardSpec, RawRankItem

log = structlog.get_logger(__name__)

# Kuwo's anonymous bang API: the endpoint its own web pages call. It answers
# plain HTTPS JSON without a session, so no cookie or csrf token is involved.
_BANG_URL = "https://kbangserver.kuwo.cn/ksong.s"
# The full bang menu only exists inside the server-rendered rank page; Kuwo's
# JSON menu endpoint refuses requests that carry no `kw_token` cookie.
_CATALOG_URL = "https://www.kuwo.cn/rankList"
_HEADERS = {"Referer": "https://www.kuwo.cn/"}
_PAGE_SIZE = 100
_MAX_PAGES = 5

# The rank page ships its data as a `__NUXT__` payload. Nuxt hoists repeated
# literals into the IIFE argument list, so a chart id reads either
# `sourceid:"93"` or `sourceid:g` with `g` defined at the end of the payload.
_GROUP_RE = re.compile(r'\{name:"(?P<group>[^"]{1,12})",list:\[(?P<charts>.*?)\]\}', re.DOTALL)
_CHART_RE = re.compile(
    r'sourceid:(?P<sourceid>"[^"]*"|[A-Za-z_$][\w$]*),intro:"[^"]*",name:"(?P<name>[^"]*)"'
)
_NUXT_PARAMS_RE = re.compile(r"__NUXT__=\(function\((?P<params>[^)]*)\)\{")
_NUXT_ARGS_RE = re.compile(r"\}\((?P<args>[^()]*)\)\)")


class KuwoCharts:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_board(self, board_config: BoardSpec) -> list[RawRankItem]:
        bang_id = board_config.extra.get("bang_id")
        if not isinstance(bang_id, int) or isinstance(bang_id, bool):
            raise ValueError("kuwo extra.bang_id must be an int")
        items: list[RawRankItem] = []
        seen_ids: set[str] = set()
        total: int | None = None
        for page in range(_MAX_PAGES):
            payload = await self._fetch_page(bang_id, page)
            total = _total(payload, total)
            rows = _music_list(payload)
            added = 0
            for index, raw in enumerate(rows, start=1):
                fallback_rank = page * _PAGE_SIZE + index
                parsed = _parse_item(raw, fallback_rank)
                if parsed is None:
                    log.warning("kuwo_skip_item", board_id=board_config.id, index=fallback_rank)
                    continue
                if parsed.external_id in seen_ids:
                    continue
                seen_ids.add(parsed.external_id)
                items.append(parsed)
                added += 1
            if not rows or len(rows) < _PAGE_SIZE or added == 0:
                break
            if total is not None and (page + 1) * _PAGE_SIZE >= total:
                break
        return items

    async def _fetch_page(self, bang_id: int, page: int) -> Any:
        response = await self._client.get(
            _BANG_URL,
            params={
                "from": "pc",
                "fmt": "json",
                "type": "bang",
                "data": "content",
                "id": bang_id,
                # Kuwo pages its bang songs from zero.
                "pn": page,
                "rn": _PAGE_SIZE,
            },
            headers=_HEADERS,
        )
        response.raise_for_status()
        return response.json()

    async def list_catalog(self) -> list[dict[str, Any]]:
        response = await self._client.get(_CATALOG_URL, headers=_HEADERS)
        response.raise_for_status()
        return parse_catalog_page(response.text)


def parse_catalog_page(html: str) -> list[dict[str, Any]]:
    """Read the bang menu out of the server-rendered rank page.

    The page publishes every chart the site offers, grouped the way Kuwo groups
    them, so the catalog stays current without a hardcoded id list.
    """
    start = html.find("__NUXT__")
    if start < 0:
        return []
    payload = html[start:]
    constants = _nuxt_constants(payload)
    groups: list[dict[str, Any]] = []
    for group in _GROUP_RE.finditer(payload):
        charts: list[dict[str, Any]] = []
        for chart in _CHART_RE.finditer(group.group("charts")):
            key = _chart_key(chart.group("sourceid"), constants)
            name = chart.group("name")
            if key is None or not name:
                continue
            charts.append({"key": key, "name": name, "playable": True})
        if charts:
            groups.append({"name": group.group("group"), "charts": charts})
    return groups


def _nuxt_constants(payload: str) -> dict[str, str]:
    """Resolve the literals Nuxt hoisted into the payload's IIFE arguments."""
    params = _NUXT_PARAMS_RE.search(payload)
    args = _NUXT_ARGS_RE.search(payload)
    if params is None or args is None:
        return {}
    names = [name.strip() for name in params.group("params").split(",")]
    values = [_quoted(arg) for arg in args.group("args").split(",")]
    return {
        name: value
        for name, value in zip(names, values, strict=False)
        if name and value
    }


def _chart_key(token: str, constants: dict[str, str]) -> str | None:
    value = _quoted(token) if token.startswith('"') else constants.get(token, "")
    return value if value.isdigit() else None


def _quoted(token: str) -> str:
    value = token.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return ""


def _music_list(payload: Any) -> list[Any]:
    rows = payload.get("musiclist") if isinstance(payload, dict) else None
    return rows if isinstance(rows, list) else []


def _total(payload: Any, current: int | None) -> int | None:
    value = payload.get("num") if isinstance(payload, dict) else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return current


def _parse_item(raw: object, rank: int) -> RawRankItem | None:
    if not isinstance(raw, dict):
        return None
    song_id = raw.get("id")
    title = raw.get("name")
    if not _digits(song_id) or not isinstance(title, str) or not title:
        return None
    return RawRankItem(
        rank=rank,
        external_id=str(song_id),
        title=title,
        artist=_artist(raw),
        album=_text(raw.get("album")),
        duration_ms=_duration_ms(raw.get("song_duration")),
        # The bang endpoint publishes no per-song cover, only the chart's own
        # artwork, so a Kuwo rank row shows the player placeholder.
        cover_url=None,
        official_url=_official_url(str(song_id)),
    )


def _artist(raw: dict[str, Any]) -> str:
    return _text(raw.get("artist")) or "未知"


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _digits(value: object) -> bool:
    return isinstance(value, str) and value.isdigit()


def _duration_ms(value: object) -> int | None:
    seconds = int(value) if isinstance(value, str) and value.isdigit() else value
    if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds > 0:
        return seconds * 1000
    return None


def _official_url(song_id: str) -> str:
    return f"https://www.kuwo.cn/play_detail/{song_id}"


def create_chart(client: httpx.AsyncClient) -> KuwoCharts:
    return KuwoCharts(client)

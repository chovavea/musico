from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.models import BoardSpec
from app.domain.normalize import normalized_score
from app.plugins._registry import PluginRegistry


def chart_key_for_spec(spec: BoardSpec) -> str | None:
    extra = spec.extra
    if spec.platform == "qqmusic" and isinstance(extra.get("top_id"), int):
        return str(extra["top_id"])
    if spec.platform == "netease" and extra.get("playlist_id"):
        return str(extra["playlist_id"])
    return None


_NON_SONG_MARKERS = ("MV", "视频榜", "专辑榜", "歌手榜")


def is_song_chart(*, key: str, name: str, playable: bool = True) -> bool:
    if not playable:
        return False
    if key == "201":
        return False
    return not any(marker in name for marker in _NON_SONG_MARKERS)


def song_chart_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        charts: list[dict[str, Any]] = []
        for chart in group.get("charts") or []:
            if not isinstance(chart, dict):
                continue
            name = str(chart.get("name") or "")
            key = str(chart.get("key") or "")
            playable = chart.get("playable", True)
            if not is_song_chart(key=key, name=name, playable=bool(playable)):
                continue
            charts.append(chart)
        if charts:
            result.append({**group, "charts": charts})
    return result


def flatten_catalog_charts(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name") or "")
        for chart in group.get("charts") or []:
            if not isinstance(chart, dict):
                continue
            items.append({**chart, "group": group_name, "key": str(chart.get("key") or "")})
    return items


def sorted_catalog_charts(
    groups: list[dict[str, Any]],
    order_map: dict[str, int],
) -> list[dict[str, Any]]:
    items = flatten_catalog_charts(groups)
    max_saved = max(order_map.values()) if order_map else 0
    next_new = max_saved + 10
    annotated: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        key = str(item.get("key") or "")
        chart = {**item, "key": key}
        if key in order_map:
            chart["sort_order"] = int(order_map[key])
        elif order_map:
            chart["sort_order"] = next_new
            next_new += 10
        else:
            chart["sort_order"] = index * 10
        annotated.append(chart)
    annotated.sort(key=lambda chart: (int(chart["sort_order"]), str(chart["key"])))
    return annotated


def apply_catalog_order(
    groups: list[dict[str, Any]],
    order_map: dict[str, int],
) -> list[dict[str, Any]]:
    ordered = sorted_catalog_charts(groups, order_map)
    by_key = {str(item["key"]): int(item["sort_order"]) for item in ordered}
    result: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        charts: list[dict[str, Any]] = []
        for chart in group.get("charts") or []:
            if not isinstance(chart, dict):
                continue
            key = str(chart.get("key") or "")
            charts.append({**chart, "key": key, "sort_order": by_key.get(key, 10_000)})
        charts.sort(key=lambda chart: (int(chart["sort_order"]), str(chart["key"])))
        if charts:
            result.append({**group, "charts": charts})
    result.sort(
        key=lambda group: min(
            (int(chart["sort_order"]) for chart in group["charts"]),
            default=10_000,
        )
    )
    return result


def catalog_chart_keys(groups: list[dict[str, Any]], order_map: dict[str, int]) -> list[str]:
    return [str(item["key"]) for item in sorted_catalog_charts(groups, order_map)]


def insert_chart_before(
    keys: list[str],
    chart_key: str,
    before_key: str | None,
) -> list[str] | None:
    if chart_key not in keys:
        return None
    if before_key is not None and before_key not in keys:
        return None
    if before_key == chart_key:
        return list(keys)
    next_keys = [key for key in keys if key != chart_key]
    if before_key is None:
        next_keys.append(chart_key)
    else:
        next_keys.insert(next_keys.index(before_key), chart_key)
    return next_keys


def match_spec(specs: list[BoardSpec], platform: str, key: str) -> BoardSpec | None:
    for spec in specs:
        if spec.platform == platform and chart_key_for_spec(spec) == key:
            return spec
    return None


async def list_platform_catalog(registry: PluginRegistry, platform: str) -> list[dict[str, Any]]:
    record = registry.get(platform)
    chart = None if record is None else record.chart
    list_catalog = getattr(chart, "list_catalog", None)
    if list_catalog is None:
        raise ValueError(f"platform has no catalog: {platform}")
    groups = await list_catalog()
    if not isinstance(groups, list):
        raise ValueError(f"{platform} catalog must be a list")
    return song_chart_groups(groups)


def live_spec(platform: str, key: str, name: str) -> BoardSpec:
    extra: dict[str, Any]
    if platform == "qqmusic":
        extra = {"top_id": int(key)}
    elif platform == "netease":
        extra = {"playlist_id": key}
    else:
        extra = {}
    return BoardSpec(
        id=f"catalog:{platform}:{key}",
        platform=platform,
        name=name,
        type="catalog",
        interval_sec=1800,
        enabled=True,
        extra=extra,
    )


def payload_from_raw(spec: BoardSpec, items: list[Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    n = len(items)
    entries: list[dict[str, Any]] = []
    for raw in items:
        entries.append(
            {
                "rank": raw.rank,
                "previous_rank": None,
                "normalized_score": normalized_score(raw.rank, n),
                "raw_score": raw.raw_score,
                "title": raw.title,
                "artist": raw.artist,
                "cover_url": raw.cover_url,
                "official_url": raw.official_url,
                "external_id": raw.external_id,
                "platform": spec.platform,
                "preview_url": raw.preview_url,
                "quality": raw.preview_quality,
                "expire_at": raw.preview_expire_at.isoformat() if raw.preview_expire_at else None,
            }
        )
    iso = now.isoformat()
    return {
        "board_id": spec.id,
        "fetched_at": iso,
        "updated_at": iso,
        "staleness": "fresh",
        "items": entries,
        "live": True,
    }

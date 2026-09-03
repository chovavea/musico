from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.adapters.http.envelope import fail, ok
from app.adapters.http.preview import stream_official_preview
from app.adapters.persistence.repository import ChartRepository
from app.domain.models import BoardSpec
from app.services.catalog import (
    apply_catalog_order,
    catalog_chart_keys,
    chart_key_for_spec,
    list_platform_catalog,
    live_spec,
    match_spec,
    payload_from_raw,
)
from app.services.health import build_health, compute_staleness


class MoveBoardIn(BaseModel):
    direction: Literal["up", "down"]


class ReorderCatalogIn(BaseModel):
    before_key: str | None = None


def _board_item(spec: BoardSpec, sort_order: int) -> dict[str, Any]:
    return {
        "id": spec.id,
        "platform": spec.platform,
        "name": spec.name,
        "type": spec.type,
        "enabled": spec.enabled,
        "interval_sec": spec.interval_sec,
        "extra": spec.extra,
        "chart_key": chart_key_for_spec(spec),
        "sort_order": sort_order,
    }


def _sorted_boards(specs: list[BoardSpec], order: dict[str, int]) -> list[dict[str, Any]]:
    items = [_board_item(spec, order.get(spec.id, 10_000)) for spec in specs]
    items.sort(key=lambda item: (int(item["sort_order"]), str(item["id"])))
    return items


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/platforms")
    async def platforms(request: Request) -> Any:
        names = request.app.state.registry.platform_names()
        return ok([{"id": key, "name": value} for key, value in names.items()])

    @router.get("/boards")
    async def boards(request: Request) -> Any:
        specs: list[BoardSpec] = request.app.state.board_specs
        async with request.app.state.session_factory() as session:
            order = await ChartRepository(session).board_sort_map()
        return ok(_sorted_boards(specs, order))

    @router.post("/boards/{board_id}/move")
    async def move_board(board_id: str, payload: MoveBoardIn, request: Request) -> Any:
        spec = _find_spec(request, board_id)
        if spec is None:
            return fail(40401, "board not found", status_code=404)
        specs: list[BoardSpec] = request.app.state.board_specs
        async with request.app.state.session_factory() as session:
            repo = ChartRepository(session)
            moved = await repo.move_board(
                board_id,
                payload.direction,
                {item.id for item in specs},
            )
            if not moved:
                return fail(40401, "board not found", status_code=404)
            await session.commit()
            order = await repo.board_sort_map()
        return ok(_sorted_boards(specs, order))

    @router.get("/boards/{board_id}")
    async def board_detail(board_id: str, request: Request) -> Any:
        spec = _find_spec(request, board_id)
        if spec is None:
            return fail(40401, "board not found", status_code=404)
        return ok(spec.model_dump())

    @router.get("/boards/{board_id}/latest")
    async def board_latest(board_id: str, request: Request) -> Any:
        spec = _find_spec(request, board_id)
        if spec is None:
            return fail(40401, "board not found", status_code=404)
        cache: dict[str, Any] = request.app.state.latest_cache
        cached = cache.get(f"latest:{board_id}")
        now_ts = datetime.now().timestamp()
        ttl = request.app.state.settings.latest_cache_ttl_sec
        if cached and now_ts - cached["ts"] < ttl:
            return ok(cached["data"])
        async with request.app.state.session_factory() as session:
            repo = ChartRepository(session)
            payload = await repo.get_latest_payload(board_id)
        if payload is None:
            data = {
                "board_id": board_id,
                "staleness": "missing",
                "items": [],
            }
            return fail(40402, "snapshot missing", status_code=404, data=data)
        updated_at: datetime = payload.pop("updated_at_dt")
        payload["staleness"] = compute_staleness(
            updated_at,
            spec.interval_sec,
            request.app.state.settings.staleness_multiplier,
        )
        return ok(payload)

    @router.get("/catalog")
    async def catalog(request: Request) -> Any:
        return ok(await _catalog_payload(request))

    @router.post("/catalog/{platform}/charts/{chart_key}/move")
    async def move_catalog_chart(
        platform: str,
        chart_key: str,
        payload: MoveBoardIn,
        request: Request,
    ) -> Any:
        names = request.app.state.registry.platform_names()
        if platform not in names:
            return fail(40401, "platform not found", status_code=404)
        raw = await _raw_catalog_platforms(request)
        groups = next((item["groups"] for item in raw if item["id"] == platform), [])
        if not groups:
            return fail(40401, "catalog unavailable", status_code=404)
        async with request.app.state.session_factory() as session:
            repo = ChartRepository(session)
            keys = catalog_chart_keys(groups, await repo.catalog_order_map(platform))
            moved = await repo.move_catalog_chart(platform, chart_key, payload.direction, keys)
            if not moved:
                return fail(40401, "chart not found", status_code=404)
            await session.commit()
            order = await repo.catalog_order_map(platform)
        return ok(
            {
                "id": platform,
                "name": names[platform],
                "groups": apply_catalog_order(groups, order),
            }
        )

    @router.post("/catalog/{platform}/charts/{chart_key}/reorder")
    async def reorder_catalog_chart(
        platform: str,
        chart_key: str,
        payload: ReorderCatalogIn,
        request: Request,
    ) -> Any:
        names = request.app.state.registry.platform_names()
        if platform not in names:
            return fail(40401, "platform not found", status_code=404)
        raw = await _raw_catalog_platforms(request)
        groups = next((item["groups"] for item in raw if item["id"] == platform), [])
        if not groups:
            return fail(40401, "catalog unavailable", status_code=404)
        async with request.app.state.session_factory() as session:
            repo = ChartRepository(session)
            keys = catalog_chart_keys(groups, await repo.catalog_order_map(platform))
            moved = await repo.reorder_catalog_chart(
                platform, chart_key, payload.before_key, keys
            )
            if not moved:
                return fail(40401, "chart not found", status_code=404)
            await session.commit()
            order = await repo.catalog_order_map(platform)
        return ok(
            {
                "id": platform,
                "name": names[platform],
                "groups": apply_catalog_order(groups, order),
            }
        )

    @router.get("/catalog/{platform}/{chart_key}/latest")
    async def catalog_latest(platform: str, chart_key: str, request: Request) -> Any:
        specs: list[BoardSpec] = request.app.state.board_specs
        yaml_spec = match_spec(specs, platform, chart_key)
        if yaml_spec is not None:
            return await board_latest(yaml_spec.id, request)
        cache: dict[str, Any] = request.app.state.latest_cache
        cache_key = f"catalog:{platform}:{chart_key}"
        now_ts = datetime.now().timestamp()
        cached = cache.get(cache_key)
        ttl = request.app.state.settings.latest_cache_ttl_sec
        if cached and now_ts - cached["ts"] < ttl:
            return ok(cached["data"])
        record = request.app.state.registry.get(platform)
        if record is None or record.chart is None:
            return fail(40401, "platform not found", status_code=404)
        spec = live_spec(platform, chart_key, chart_key)
        try:
            items = await record.chart.fetch_board(spec)
        except Exception as exc:
            return fail(50201, str(exc)[:200], status_code=502)
        payload = payload_from_raw(spec, items)
        cache[cache_key] = {"ts": now_ts, "data": payload}
        return ok(payload)

    @router.get("/preview/{platform}/{external_id}/stream")
    async def preview_stream(platform: str, external_id: str, request: Request) -> StreamingResponse:
        return await stream_official_preview(request, platform, external_id)

    @router.get("/health")
    async def health(request: Request) -> Any:
        data = await build_health(
            request.app.state.session_factory,
            request.app.state.board_specs,
            request.app.state.settings,
        )
        return ok(data)

    return router


async def _raw_catalog_platforms(request: Request) -> list[dict[str, Any]]:
    cache: dict[str, Any] = request.app.state.latest_cache
    cached = cache.get("catalog:raw")
    now_ts = datetime.now().timestamp()
    if cached and now_ts - cached["ts"] < 600:
        return cached["data"]
    registry = request.app.state.registry
    platforms: list[dict[str, Any]] = []
    for platform_id, name in registry.platform_names().items():
        try:
            groups = await list_platform_catalog(registry, platform_id)
        except Exception:
            groups = []
        platforms.append({"id": platform_id, "name": name, "groups": groups})
    cache["catalog:raw"] = {"ts": now_ts, "data": platforms}
    cache.pop("catalog:all", None)
    return platforms


async def _catalog_payload(request: Request) -> dict[str, Any]:
    raw = await _raw_catalog_platforms(request)
    platforms: list[dict[str, Any]] = []
    async with request.app.state.session_factory() as session:
        repo = ChartRepository(session)
        for item in raw:
            order = await repo.catalog_order_map(item["id"])
            platforms.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "groups": apply_catalog_order(item["groups"], order),
                }
            )
    return {"platforms": platforms}


def _find_spec(request: Request, board_id: str) -> BoardSpec | None:
    specs: list[BoardSpec] = request.app.state.board_specs
    for spec in specs:
        if spec.id == board_id:
            return spec
    return None

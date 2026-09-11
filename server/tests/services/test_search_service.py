from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.domain.models import TrackRef
from app.plugins._registry import PluginRecord, PluginRegistry
from app.services.search import SearchService


def track(
    platform: str,
    external_id: str,
    *,
    title: str = "我不难过",
    artist: str = "孙燕姿",
    duration_ms: int | None = 320_000,
    isrc: str | None = None,
) -> TrackRef:
    return TrackRef(
        platform=platform,
        external_id=external_id,
        title=title,
        artist=artist,
        duration_ms=duration_ms,
        isrc=isrc,
    )


class FakeSearch:
    def __init__(self, tracks: list[TrackRef] | None = None, error: Exception | None = None):
        self.tracks = tracks or []
        self.error = error
        self.calls: list[str] = []

    async def search(self, query: Any) -> list[TrackRef]:
        self.calls.append(query.title)
        if self.error:
            raise self.error
        return self.tracks


def service_with(*records: PluginRecord) -> SearchService:
    registry = PluginRegistry(
        plugins={record.plugin_id: record for record in records},
    )
    service = SearchService(registry, None)  # type: ignore[arg-type]

    async def no_annotations(_tracks: list[TrackRef]) -> dict[tuple[str, str], dict[str, Any]]:
        return {}

    service._library_annotations = no_annotations  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
async def test_search_runs_platforms_in_parallel_and_merges_same_recording() -> None:
    qq = FakeSearch([track("qqmusic", "qq-1")])
    netease = FakeSearch([track("netease", "163-1")])
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=netease),  # type: ignore[arg-type]
    )

    payload = await service.search("我不难过", kind="full")

    assert len(payload["items"]) == 1
    assert payload["items"][0]["platform_count"] == 2
    assert {item["platform"] for item in payload["items"][0]["platforms"]} == {
        "qqmusic",
        "netease",
    }
    assert [item["status"] for item in payload["platforms"]] == ["ok", "ok"]
    assert qq.calls == ["我不难过"]
    assert netease.calls == ["我不难过"]


@pytest.mark.asyncio
async def test_search_keeps_version_and_duration_variants_separate() -> None:
    qq = FakeSearch(
        [
            track("qqmusic", "qq-1"),
            track("qqmusic", "qq-live", title="我不难过 (Live)"),
        ]
    )
    netease = FakeSearch(
        [
            track("netease", "163-live", title="我不难过 (Live)"),
            track("netease", "163-slow", duration_ms=340_000),
        ]
    )
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=netease),  # type: ignore[arg-type]
    )

    payload = await service.search("我不难过")

    assert len(payload["items"]) == 3


@pytest.mark.asyncio
async def test_search_reports_partial_provider_failure_without_hiding_results() -> None:
    qq = FakeSearch([track("qqmusic", "qq-1")])
    netease = FakeSearch(error=RuntimeError("upstream unavailable"))
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=netease),  # type: ignore[arg-type]
    )

    payload = await service.search("我不难过", kind="suggest", limit=5)

    assert payload["partial"] is True
    assert payload["items"][0]["external_id"] == "qq-1"
    assert [item["status"] for item in payload["platforms"]] == ["ok", "error"]


@pytest.mark.asyncio
async def test_search_prefers_a_library_candidate_when_platforms_are_merged() -> None:
    qq = FakeSearch([track("qqmusic", "qq-1")])
    netease = FakeSearch([track("netease", "163-1")])
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=netease),  # type: ignore[arg-type]
    )

    async def annotations(_tracks: list[TrackRef]) -> dict[tuple[str, str], dict[str, Any]]:
        return {("qqmusic", "qq-1"): {"library_status": "ready", "library_asset_id": "asset-1"}}

    service._library_annotations = annotations  # type: ignore[method-assign]
    payload = await service.search("我不难过")

    assert payload["items"][0]["platform"] == "qqmusic"
    assert payload["items"][0]["library_status"] == "ready"
    assert payload["items"][0]["library_asset_id"] == "asset-1"


@pytest.mark.asyncio
async def test_search_does_not_call_platforms_for_a_short_query() -> None:
    qq = FakeSearch([track("qqmusic", "qq-1")])
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
    )

    payload = await service.search("我", kind="suggest")

    assert payload["reason"] == "query_too_short"
    assert qq.calls == []


@pytest.mark.asyncio
async def test_search_keeps_best_platform_rank_when_merging() -> None:
    netease = FakeSearch(
        [track("netease", f"n-{index}", title=f"网易独有{index}") for index in range(19)]
        + [track("netease", "n-hit")]
    )
    qq = FakeSearch(
        [track("qqmusic", "q-hit")]
        + [track("qqmusic", f"q-{index}", title=f"QQ独有{index}") for index in range(19)]
    )
    service = service_with(
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=netease),  # type: ignore[arg-type]
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
    )

    payload = await service.search("我不难过", kind="full", limit=20)

    merged = next(
        item
        for item in payload["items"]
        if {source["external_id"] for source in item["platforms"]} == {"n-hit", "q-hit"}
    )
    assert merged["platform_count"] == 2
    assert payload["items"].index(merged) <= 1


@pytest.mark.asyncio
async def test_search_cache_refreshes_library_annotations() -> None:
    qq = FakeSearch([track("qqmusic", "qq-1")])
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
    )
    calls = {"count": 0}

    async def annotations(_tracks: list[TrackRef]) -> dict[tuple[str, str], dict[str, Any]]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {}
        return {("qqmusic", "qq-1"): {"library_status": "ready", "library_asset_id": "asset-1"}}

    service._library_annotations = annotations  # type: ignore[method-assign]

    first = await service.search("我不难过")
    second = await service.search("我不难过")

    assert qq.calls == ["我不难过"]
    assert first["items"][0]["library_status"] is None
    assert second["items"][0]["library_status"] == "ready"
    assert second["items"][0]["library_asset_id"] == "asset-1"


@dataclass
class FakeLibraryTrack:
    id: str
    title: str
    artist: str
    album: str | None = None
    duration_ms: int | None = 320_000
    isrc: str | None = None
    version: str | None = None


@dataclass
class FakeLibraryAsset:
    id: str
    status: str = "ready"


@pytest.mark.asyncio
async def test_search_does_not_mark_live_variant_as_local_studio() -> None:
    qq = FakeSearch(
        [
            track("qqmusic", "qq-1"),
            track("qqmusic", "qq-live", title="我不难过 (Live)", duration_ms=309_000),
        ]
    )
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
    )
    studio_row = FakeLibraryTrack(id="lib-studio", title="我不难过", artist="孙燕姿")
    studio_asset = FakeLibraryAsset(id="asset-studio")

    async def annotations(tracks: list[TrackRef]) -> dict[tuple[str, str], dict[str, Any]]:
        return SearchService._annotate_tracks(
            tracks,
            [studio_row],
            {studio_row.id: studio_asset},
            {},
        )

    service._library_annotations = annotations  # type: ignore[method-assign]
    payload = await service.search("我不难过")

    by_id = {item["external_id"]: item for item in payload["items"]}
    assert by_id["qq-1"]["library_status"] == "ready"
    assert by_id["qq-1"]["library_asset_id"] == "asset-studio"
    assert by_id["qq-live"]["library_status"] is None
    assert by_id["qq-live"]["library_asset_id"] is None


def test_annotate_tracks_attaches_live_library_only_to_live_search_hit() -> None:
    studio = track("qqmusic", "qq-1")
    live = track("qqmusic", "qq-live", title="我不难过 (Live)", duration_ms=309_000)
    live_row = FakeLibraryTrack(
        id="lib-live",
        title="我不难过 (Live)",
        artist="孙燕姿",
        duration_ms=309_000,
    )
    live_asset = FakeLibraryAsset(id="asset-live")

    annotations = SearchService._annotate_tracks(
        [studio, live],
        [live_row],
        {live_row.id: live_asset},
        {},
    )

    assert ("qqmusic", "qq-1") not in annotations
    assert annotations[("qqmusic", "qq-live")]["library_asset_id"] == "asset-live"
    assert annotations[("qqmusic", "qq-live")]["library_status"] == "ready"

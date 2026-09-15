from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import pytest
import structlog
from app.domain.matching import is_same_recording
from app.domain.models import TrackRef
from app.plugins._registry import PluginRecord, PluginRegistry
from app.services import search as search_module
from app.services.search import SearchService, _SearchCandidate, _SearchGroup


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
    def __init__(
        self,
        tracks: list[TrackRef] | None = None,
        error: Exception | None = None,
        delay: float = 0.0,
    ):
        self.tracks = tracks or []
        self.error = error
        self.delay = delay
        self.calls: list[str] = []
        self.limits: list[int] = []

    async def search(self, query: Any) -> list[TrackRef]:
        self.calls.append(query.title)
        self.limits.append(query.limit)
        if self.delay:
            await asyncio.sleep(self.delay)
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


def candidates(*items: tuple[str, str, dict[str, Any]]) -> list[_SearchCandidate]:
    return [
        _SearchCandidate(
            track=track(platform, external_id, **fields),
            search_rank=rank,
        )
        for rank, (platform, external_id, fields) in enumerate(items)
    ]


def all_pairs_merge(source: list[_SearchCandidate]) -> list[_SearchGroup]:
    """Reference implementation: the all-pairs scan the bucketed merge replaced."""
    groups: list[_SearchGroup] = []
    seen: set[tuple[str, str]] = set()
    for candidate in source:
        item = candidate.track
        identity = (item.platform, item.external_id)
        if identity in seen:
            continue
        seen.add(identity)
        matching = next(
            (
                group
                for group in groups
                if any(
                    existing.track.platform != item.platform
                    and is_same_recording(existing.track, item)
                    for existing in group.candidates
                )
            ),
            None,
        )
        if matching is None:
            groups.append(
                _SearchGroup(
                    candidates=[candidate],
                    first_rank=candidate.search_rank,
                    first_platform=item.platform,
                )
            )
        else:
            matching.candidates.append(candidate)
            if candidate.search_rank < matching.first_rank or (
                candidate.search_rank == matching.first_rank
                and item.platform < matching.first_platform
            ):
                matching.first_rank = candidate.search_rank
                matching.first_platform = item.platform
    groups.sort(key=lambda group: (group.first_rank, group.first_platform))
    return groups


def grouping(groups: list[_SearchGroup]) -> list[tuple[int, str, tuple[tuple[str, str], ...]]]:
    def identities(group: _SearchGroup) -> tuple[tuple[str, str], ...]:
        entries = ((item.track.platform, item.track.external_id) for item in group.candidates)
        return tuple(sorted(entries))

    return [
        (
            group.first_rank,
            group.first_platform,
            identities(group),
        )
        for group in groups
    ]


@pytest.mark.asyncio
async def test_bucketed_merge_matches_the_all_pairs_grouping() -> None:
    service = SearchService(PluginRegistry(), None)  # type: ignore[arg-type]
    source = candidates(
        ("qqmusic", "qq-1", {"title": "我不难过"}),
        ("netease", "163-1", {"title": "我不难过", "duration_ms": 320_400}),
        ("kugou", "kg-1", {"title": "我不难过 (Live)", "duration_ms": 297_000}),
        ("qqmusic", "qq-live", {"title": "我不难过 (Live)", "duration_ms": 297_000}),
        ("kuwo", "kw-1", {"title": "告白氣球", "artist": "周杰倫"}),
        ("netease", "163-2", {"title": "告白气球", "artist": "周杰伦", "duration_ms": 321_000}),
        ("kuwo", "kw-2", {"title": "夜曲", "isrc": "TW-A1"}),
        ("qqmusic", "qq-2", {"title": "Nocturne", "artist": "周杰伦", "isrc": "tw-a1"}),
        ("qqmusic", "qq-1", {"title": "我不难过"}),
        ("kugou", "kg-2", {"title": "同名不同歌手", "artist": "其他歌手"}),
        ("netease", "163-3", {"title": "同名不同歌手", "artist": "孙燕姿"}),
        ("kuwo", "kw-3", {"title": "独有曲目"}),
    )

    merged = service._merge_tracks(list(source))

    assert grouping(merged) == grouping(all_pairs_merge(list(source)))
    # 同一录音跨平台合并、live 版两条互相合并、繁简合并、仅 ISRC 相同的跨语种标题合并，
    # 同名不同歌手与独有曲目各自成组；live 版不会并回录音室版（时长差超过 5s 阈值）。
    assert [(group.first_rank, len(group.candidates)) for group in merged] == [
        (0, 2),  # 我不难过：QQ + 网易云
        (2, 2),  # 我不难过 (Live)：酷狗 + QQ
        (4, 2),  # 告白氣球 / 告白气球：酷我 + 网易云（繁简折叠）
        (6, 2),  # 夜曲 / Nocturne：同一 ISRC
        (9, 1),  # 同名不同歌手（其他歌手）
        (10, 1),  # 同名不同歌手（孙燕姿）
        (11, 1),  # 独有曲目
    ]


def test_merge_buckets_by_title_and_artist(monkeypatch: pytest.MonkeyPatch) -> None:
    """A popular single must not be compared against other artists' same titles."""
    calls: list[tuple[str, str]] = []
    original = search_module.is_same_recording

    def spy(left: TrackRef, right: TrackRef) -> bool:
        calls.append((left.external_id, right.external_id))
        return original(left, right)

    monkeypatch.setattr(search_module, "is_same_recording", spy)
    service = SearchService(PluginRegistry(), None)  # type: ignore[arg-type]
    platforms = ["qqmusic", "netease", "kugou", "kuwo"]
    singles = candidates(
        *[
            (
                platforms[index % len(platforms)],
                f"id-{index}",
                {"title": "告白气球", "artist": f"歌手{index}"},
            )
            for index in range(40)
        ]
    )

    merged = service._merge_tracks(singles)

    assert len(merged) == 40
    assert calls == []


def test_merge_still_joins_multi_artist_spellings_of_one_recording() -> None:
    """The (title, artist) bucket must not lose cross-platform spellings."""
    service = SearchService(PluginRegistry(), None)  # type: ignore[arg-type]
    shared = candidates(
        ("qqmusic", "qq-1", {"title": "告白气球", "artist": "周杰伦"}),
        ("netease", "163-1", {"title": "告白气球", "artist": "周杰伦 / 蔡依林"}),
        ("kugou", "kg-1", {"title": "告白气球", "artist": "周杰伦"}),
    )

    merged = service._merge_tracks(shared)

    assert len(merged) == 1
    assert len(merged[0].candidates) == 3

    # A shared featured name alone is not a match: the lead artist must agree.
    featured = candidates(
        ("qqmusic", "qq-2", {"title": "告白气球", "artist": "周杰伦"}),
        ("kugou", "kg-2", {"title": "告白气球", "artist": "蔡依林"}),
    )
    assert len(service._merge_tracks(featured)) == 2


@pytest.mark.asyncio
async def test_merge_folds_traditional_and_simplified_titles() -> None:
    service = SearchService(PluginRegistry(), None)  # type: ignore[arg-type]
    source = candidates(
        ("qqmusic", "qq-1", {"title": "告白气球", "artist": "周杰伦"}),
        ("kuwo", "kw-1", {"title": "告白氣球", "artist": "周傑倫"}),
    )

    merged = service._merge_tracks(source)

    assert len(merged) == 1
    assert len(merged[0].candidates) == 2


@pytest.mark.asyncio
async def test_merge_keeps_folded_live_variants_separate_from_the_studio_take() -> None:
    service = SearchService(PluginRegistry(), None)  # type: ignore[arg-type]
    source = candidates(
        ("qqmusic", "qq-1", {"title": "晴天", "artist": "周杰伦"}),
        ("kuwo", "kw-1", {"title": "晴天 (現場)", "artist": "周杰倫", "duration_ms": 240_000}),
    )

    merged = service._merge_tracks(source)

    assert [len(group.candidates) for group in merged] == [1, 1]


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
async def test_search_logs_a_platform_that_failed() -> None:
    """A rejected or throttled platform must leave a trace somewhere."""
    qq = FakeSearch([track("qqmusic", "qq-1")])
    netease = FakeSearch(error=ValueError("netease search rejected the request: code=2001"))
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=netease),  # type: ignore[arg-type]
    )

    with structlog.testing.capture_logs() as entries:
        await service.search("我不难过", kind="suggest", limit=5)

    failures = [entry for entry in entries if entry["event"] == "search_platform_failed"]
    assert len(failures) == 1
    assert failures[0]["log_level"] == "warning"
    assert failures[0]["platform"] == "netease"
    assert failures[0]["error_type"] == "ValueError"
    assert "code=2001" in failures[0]["error"]


@pytest.mark.asyncio
async def test_search_filters_unrelated_provider_fallbacks() -> None:
    netease = FakeSearch(
        [
            track("netease", "unrelated", title="后来", artist="刘若英"),
            track("netease", "partial", title="我不难过 (Live)", artist="孙燕姿"),
        ]
    )
    service = service_with(
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=netease),  # type: ignore[arg-type]
    )

    payload = await service.search("不难过", kind="full")

    assert [item["external_id"] for item in payload["items"]] == ["partial"]
    assert payload["platforms"][0]["result_count"] == 1


@pytest.mark.asyncio
async def test_search_matches_title_and_artist_terms_in_either_order() -> None:
    qq = FakeSearch(
        [
            track("qqmusic", "match"),
            track("qqmusic", "wrong-artist", artist="张惠妹"),
        ]
    )
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
    )

    payload = await service.search("孙燕姿 我不难过")

    assert [item["external_id"] for item in payload["items"]] == ["match"]


@pytest.mark.asyncio
async def test_search_keeps_provider_hits_for_cross_script_queries() -> None:
    netease = FakeSearch(
        [
            track("netease", "jay-1", title="晴天", artist="周杰伦"),
            track("netease", "jay-2", title="屋顶", artist="周杰伦 / 温岚"),
        ]
    )
    service = service_with(
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=netease),  # type: ignore[arg-type]
    )

    payload = await service.search("Jay Chou")

    assert [item["external_id"] for item in payload["items"]] == ["jay-1", "jay-2"]
    assert payload["platforms"][0]["result_count"] == 2


@pytest.mark.asyncio
async def test_search_matches_simplified_query_to_traditional_artist() -> None:
    netease = FakeSearch(
        [
            track("netease", "lemon", title="Lemon", artist="米津玄師"),
            track("netease", "unrelated", title="后来", artist="刘若英"),
        ]
    )
    service = service_with(
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=netease),  # type: ignore[arg-type]
    )

    payload = await service.search("Lemon 米津玄师")

    assert [item["external_id"] for item in payload["items"]] == ["lemon"]
    assert payload["platforms"][0]["result_count"] == 1


@pytest.mark.asyncio
async def test_search_drops_unrelated_hits_for_cjk_queries() -> None:
    netease = FakeSearch(
        [
            track("netease", "hot-1", title="后来", artist="刘若英"),
            track("netease", "hot-2", title="平凡之路", artist="朴树"),
        ]
    )
    service = service_with(
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=netease),  # type: ignore[arg-type]
    )

    payload = await service.search("晴天")

    assert payload["items"] == []
    assert payload["platforms"][0]["result_count"] == 0


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
async def test_search_does_not_call_platforms_for_a_blank_query() -> None:
    qq = FakeSearch([track("qqmusic", "qq-1")])
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
    )

    payload = await service.search("   ", kind="suggest")

    assert payload["reason"] == "query_too_short"
    assert qq.calls == []


@pytest.mark.asyncio
async def test_search_calls_platforms_for_a_single_character_query() -> None:
    qq = FakeSearch([track("qqmusic", "qq-1")])
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
    )

    payload = await service.search("孙", kind="suggest")

    assert qq.calls == ["孙"]
    assert [item["title"] for item in payload["items"]] == ["我不难过"]


@pytest.mark.asyncio
async def test_search_uses_the_default_limit_of_each_kind() -> None:
    qq = FakeSearch([track("qqmusic", "qq-1")])
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
    )

    await service.search("我不难过", kind="suggest")
    await service.search("我不难过", kind="full")

    assert qq.limits == [5, 100]


@pytest.mark.asyncio
async def test_search_clamps_the_requested_limit_to_the_maximum() -> None:
    qq = FakeSearch([track("qqmusic", "qq-1")])
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
    )

    payload = await service.search("孙燕姿", kind="full", limit=500)

    assert qq.limits == [100]
    assert [item["title"] for item in payload["items"]] == ["我不难过"]


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
    library_track_id: str | None = None


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


def test_annotate_tracks_matches_traditional_and_simplified_credits() -> None:
    simplified = FakeLibraryTrack(
        id="lib-1",
        title="告白气球",
        artist="周杰伦",
        duration_ms=220_000,
    )
    asset = FakeLibraryAsset(id="asset-1")
    traditional = track(
        "kuwo",
        "kw-1",
        title="告白氣球",
        artist="周杰倫",
        duration_ms=221_000,
    )

    annotations = SearchService._annotate_tracks(
        [traditional],
        [simplified],
        {simplified.id: asset},
        {},
    )

    assert annotations[("kuwo", "kw-1")]["library_asset_id"] == "asset-1"


@pytest.mark.asyncio
async def test_search_cuts_off_a_platform_that_exceeds_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(search_module, "_SEARCH_BUDGET_SEC", 0.05)
    slow = FakeSearch([track("qqmusic", "qq-1")], delay=5.0)
    fast = FakeSearch([track("netease", "163-1")])
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=slow),  # type: ignore[arg-type]
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=fast),  # type: ignore[arg-type]
    )

    started = time.perf_counter()
    payload = await service.search("我不难过", kind="full", limit=10)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0
    assert [item["platform"] for item in payload["items"]] == ["netease"]
    by_id = {item["id"]: item for item in payload["platforms"]}
    assert by_id["qqmusic"]["status"] == "error"
    assert by_id["qqmusic"]["reason"] == "timeout"
    assert by_id["netease"]["status"] == "ok"
    assert payload["partial"] is True


@pytest.mark.asyncio
async def test_search_does_not_cache_a_result_that_timed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A platform cut off by the budget must come back on the very next try."""
    monkeypatch.setattr(search_module, "_SEARCH_BUDGET_SEC", 0.05)
    slow = FakeSearch([track("qqmusic", "qq-1")], delay=5.0)
    fast = FakeSearch([track("netease", "163-1")])
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=slow),  # type: ignore[arg-type]
        PluginRecord("netease", "网易云音乐", ["search"], {}, search=fast),  # type: ignore[arg-type]
    )

    first = await service.search("我不难过", kind="full", limit=10)
    second = await service.search("我不难过", kind="full", limit=10)

    # The unanswered platform keeps the payload out of the cache, so the second
    # call fans out again instead of replaying the truncated first result.
    assert fast.calls == ["我不难过", "我不难过"]
    assert first["partial"] is True
    assert second["partial"] is True


@pytest.mark.asyncio
async def test_search_keeps_a_platform_that_finished_after_the_budget_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cancel() is a no-op on a finished task; its songs must still appear."""
    real_wait = asyncio.wait

    async def wait_until_done_but_report_pending(
        tasks: Any, timeout: float | None = None, **kwargs: Any
    ) -> Any:
        done, pending = await real_wait(tasks)
        _ = timeout, kwargs, done, pending
        return set(), set(tasks)

    monkeypatch.setattr(asyncio, "wait", wait_until_done_but_report_pending)
    qq = FakeSearch([track("qqmusic", "qq-1")])
    service = service_with(
        PluginRecord("qqmusic", "QQ音乐", ["search"], {}, search=qq),  # type: ignore[arg-type]
    )

    payload = await service.search("我不难过", kind="full", limit=10)

    assert [item["platform"] for item in payload["items"]] == ["qqmusic"]
    assert payload["platforms"][0]["status"] == "ok"
    assert payload["partial"] is False


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    def __init__(self, batches: list[list[Any]]) -> None:
        self._batches = list(batches)

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _stmt: object) -> _FakeResult:
        return _FakeResult(self._batches.pop(0) if self._batches else [])


@pytest.mark.asyncio
async def test_library_annotations_match_traditional_search_to_simplified_row() -> None:
    """Stored keys stay unfolded, so the SQL equality prefilter cannot be used."""
    row = FakeLibraryTrack(
        id="lib-1",
        title="告白气球",
        artist="周杰伦",
        duration_ms=220_000,
    )
    asset = FakeLibraryAsset(id="asset-1", library_track_id="lib-1")
    service = SearchService(PluginRegistry(), lambda: _FakeSession([[row], [asset], []]))  # type: ignore[arg-type]
    found = track(
        "kuwo",
        "kw-1",
        title="告白氣球",
        artist="周杰倫",
        duration_ms=221_000,
    )

    annotations = await service._library_annotations([found])

    assert annotations[("kuwo", "kw-1")]["library_asset_id"] == "asset-1"
    assert annotations[("kuwo", "kw-1")]["library_status"] == "ready"

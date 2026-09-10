from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from app.adapters.http import preview
from app.adapters.http.routes import build_router
from app.domain.matching import is_cross_platform_match, version_markers
from app.domain.models import (
    AudioQuality,
    DownloadCandidate,
    DownloadResponse,
    PreviewInfo,
    TrackQuery,
    TrackRef,
)
from app.download_sources.registry import DownloadSourceRecord, DownloadSourceRegistry
from app.plugins._registry import PluginRecord, PluginRegistry
from app.services import preview_telemetry
from app.services.preview_plan import PreviewPlanner, PreviewPolicy, PreviewTarget
from fastapi import FastAPI

QQ = TrackRef(
    platform="qqmusic",
    external_id="001fsNdn1zuZnA",
    title="我不难过",
    artist="孙燕姿",
    duration_ms=320_000,
)
OUTER_URL = "https://music.163.com/song/media/outer/url?id=287398.mp3"
ENDPOINT = "/api/v1/preview/qqmusic/001fsNdn1zuZnA/stream"
PARAMS = {
    "title": QQ.title,
    "artist": QQ.artist,
    "duration_ms": str(QQ.duration_ms),
}
BODY = b"Netease-official-bytes"


class Probe:
    """Shared counter proving that no two outbound searches overlap."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.peak = 0
        self.order: list[str] = []

    @asynccontextmanager
    async def track(self, platform: str) -> AsyncIterator[None]:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        self.order.append(platform)
        try:
            yield
        finally:
            self.in_flight -= 1


class CrossSearch:
    def __init__(
        self,
        results: list[TrackRef],
        *,
        platform: str = "netease",
        probe: Probe | None = None,
        delay_sec: float = 0.0,
    ) -> None:
        self.results = results
        self.platform = platform
        self.probe = probe
        self.delay_sec = delay_sec
        self.calls: list[TrackQuery] = []

    async def search(self, query: TrackQuery) -> list[TrackRef]:
        self.calls.append(query)
        if self.probe is None:
            if self.delay_sec:
                await asyncio.sleep(self.delay_sec)
            return list(self.results)
        async with self.probe.track(self.platform):
            if self.delay_sec:
                await asyncio.sleep(self.delay_sec)
            return list(self.results)


class CrossPreview:
    def __init__(self, url: str | None = OUTER_URL, quality: str | None = "low") -> None:
        self.url = url
        self.quality = quality
        self.calls: list[str] = []

    async def preview(self, track: TrackRef) -> PreviewInfo:
        self.calls.append(track.external_id)
        return PreviewInfo(preview_url=self.url, quality=self.quality)


class SilentPreview:
    async def preview(self, track: TrackRef) -> PreviewInfo:
        return PreviewInfo(preview_url=None)


class SlowPreview:
    """Answers with a usable URL, but only after the request budget is gone."""

    def __init__(self, delay_sec: float) -> None:
        self.delay_sec = delay_sec

    async def preview(self, track: TrackRef) -> PreviewInfo:
        await asyncio.sleep(self.delay_sec)
        return PreviewInfo(preview_url=OUTER_URL, quality="low")


class Source:
    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        self.searched = 0
        self.resolved = 0

    async def search(self, track: TrackRef) -> list[DownloadCandidate]:
        self.searched += 1
        return [
            DownloadCandidate(
                source_id=self.source_id,
                source_track_id="song",
                title=track.title,
                artist=track.artist,
                duration_ms=track.duration_ms,
                quality=AudioQuality(format="mp3"),
            )
        ]

    async def resolve(self, candidate: DownloadCandidate, *, offset: int = 0) -> DownloadResponse:
        self.resolved += 1
        return DownloadResponse(url=f"https://{self.source_id}.example/song.mp3", headers={})


def candidate(
    platform: str,
    *,
    title: str = QQ.title,
    artist: str = QQ.artist,
    duration_ms: int | None = 320_400,
    external_id: str = "287398",
) -> TrackRef:
    return TrackRef(
        platform=platform,
        external_id=external_id,
        title=title,
        artist=artist,
        duration_ms=duration_ms,
    )


def plugin(
    plugin_id: str,
    *,
    search: object | None = None,
    preview: object | None = None,
) -> PluginRecord:
    return PluginRecord(
        plugin_id=plugin_id,
        name=plugin_id,
        capabilities=[],
        config_schema={},
        preview=preview,
        search=search,
    )


def registry_with(
    search: object | None = None,
    netease_preview: object | None = None,
) -> PluginRegistry:
    return PluginRegistry(
        plugins={
            "qqmusic": plugin("qqmusic", preview=SilentPreview()),
            "netease": plugin("netease", search=search, preview=netease_preview),
        }
    )


def source_record(source: Source) -> DownloadSourceRecord:
    return DownloadSourceRecord(
        source_id=source.source_id,
        name=source.source_id,
        priority=0,
        hosts=(f"{source.source_id}.example",),
        config_schema={},
        source=source,
    )


async def drain(planner: PreviewPlanner) -> list[PreviewTarget]:
    return [target async for target in planner.iter_targets()]


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolver(_host: str) -> list[str]:
        return ["93.184.216.34"]

    preview_telemetry.reset_preview_telemetry()
    monkeypatch.setattr("app.adapters.http.safety._default_resolver", resolver)


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[preview_telemetry.PreviewEvent]:
    recorded: list[preview_telemetry.PreviewEvent] = []

    async def record(event: preview_telemetry.PreviewEvent, **_: object) -> None:
        recorded.append(event)

    monkeypatch.setattr(preview, "publish", record)
    return recorded


@asynccontextmanager
async def client_for(
    registry: PluginRegistry,
    sources: list[DownloadSourceRecord],
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    settings: object | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = FastAPI()
        app.include_router(build_router())
        app.state.preview_client = upstream
        app.state.registry = registry
        app.state.download_sources = DownloadSourceRegistry(
            sources={source.source_id: source for source in sources}
        )
        if settings is not None:
            app.state.settings = settings
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


def audio(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=BODY, headers={"Content-Type": "audio/mpeg"})


def music_163_only(request: httpx.Request) -> httpx.Response:
    if request.url.host == "music.163.com":
        return audio(request)
    return httpx.Response(404)


async def test_another_platform_official_preview_is_played(
    events: list[preview_telemetry.PreviewEvent],
) -> None:
    search = CrossSearch([candidate("netease")])
    official = CrossPreview()
    async with client_for(registry_with(search, official), [], music_163_only) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert response.content == BODY
    assert search.calls[0].title == QQ.title
    assert official.calls == ["287398"]
    assert [event.tier for event in events] == ["T2"]
    assert events[0].status == "ok"
    assert events[0].source_platform == "netease"
    assert events[0].source_external_id == "287398"
    assert events[0].match_score == pytest.approx(0.98)


async def test_a_live_variant_is_never_borrowed(
    events: list[preview_telemetry.PreviewEvent],
) -> None:
    search = CrossSearch([candidate("netease", title="我不难过 (Live)", duration_ms=309_106)])
    official = CrossPreview()
    async with client_for(registry_with(search, official), [], music_163_only) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 404
    assert search.calls
    assert official.calls == []
    # The live edit never plays, but netease still answered the search: the pair
    # must lose a sample so the next click can prefer another platform.
    assert [(event.tier, event.status) for event in events] == [
        ("T2", "error"),
        ("none", "error"),
    ]
    assert events[0].source_platform == "netease"


@pytest.mark.parametrize(
    "other",
    [
        candidate("netease", title="另一首歌"),
        candidate("netease", artist="另一位歌手"),
        candidate("netease", duration_ms=210_000),
        candidate("netease", external_id="287398", title="我不难过 (伴奏)"),
    ],
)
async def test_unrelated_candidates_are_rejected(other: TrackRef) -> None:
    search = CrossSearch([other])
    official = CrossPreview()
    async with client_for(registry_with(search, official), [], music_163_only) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 404
    assert official.calls == []


async def test_unplayable_cross_platform_stream_falls_back_to_download_sources(
    events: list[preview_telemetry.PreviewEvent],
) -> None:
    search = CrossSearch([candidate("netease")])
    official = CrossPreview()
    source = Source("backup")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "music.163.com":
            return httpx.Response(404)
        return audio(request)

    async with client_for(
        registry_with(search, official), [source_record(source)], handler
    ) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert response.content == BODY
    assert official.calls == ["287398"]
    assert source.resolved == 1
    assert [event.tier for event in events] == ["T2", "T3"]
    assert events[0].status == "error"
    assert events[0].source_platform == "netease"
    assert events[1].source_platform == "backup"


def two_platform_registry(
    *,
    netease_search: CrossSearch,
    qq_search: CrossSearch,
    netease_preview: CrossPreview,
    qq_preview: CrossPreview,
) -> PluginRegistry:
    return PluginRegistry(
        plugins={
            "origin": plugin("origin"),
            "netease": plugin("netease", search=netease_search, preview=netease_preview),
            "qqmusic": plugin("qqmusic", search=qq_search, preview=qq_preview),
        }
    )


async def test_the_next_platform_is_not_asked_once_one_plays(
    events: list[preview_telemetry.PreviewEvent],
) -> None:
    probe = Probe()
    netease_search = CrossSearch([candidate("netease")], probe=probe)
    qq_search = CrossSearch(
        [
            TrackRef(
                platform="qqmusic",
                external_id="002B0d2H4VRqQs",
                title=QQ.title,
                artist=QQ.artist,
                duration_ms=320_400,
            )
        ],
        platform="qqmusic",
        probe=probe,
    )
    registry = two_platform_registry(
        netease_search=netease_search,
        qq_search=qq_search,
        netease_preview=CrossPreview(),
        qq_preview=CrossPreview("https://qqmusic.qq.com/preview.m4a", "medium"),
    )
    origin = QQ.model_copy(update={"platform": "origin", "external_id": "origin-1"})
    async with client_for(registry, [], music_163_only) as client:
        response = await client.get(
            "/api/v1/preview/origin/origin-1/stream",
            params={"title": origin.title, "artist": origin.artist, "duration_ms": "320000"},
        )
    assert response.status_code == 200
    assert probe.order == ["netease"]
    assert qq_search.calls == []
    assert [event.tier for event in events] == ["T2"]


async def test_learned_rate_decides_which_platform_is_asked_first(
    events: list[preview_telemetry.PreviewEvent],
) -> None:
    probe = Probe()
    netease_search = CrossSearch([candidate("netease")], probe=probe)
    qq_search = CrossSearch(
        [
            TrackRef(
                platform="qqmusic",
                external_id="002B0d2H4VRqQs",
                title=QQ.title,
                artist=QQ.artist,
                duration_ms=320_400,
            )
        ],
        platform="qqmusic",
        probe=probe,
    )
    for _ in range(5):
        preview_telemetry.RATES.record("origin", "netease", False)
        preview_telemetry.RATES.record("origin", "qqmusic", True)
    registry = two_platform_registry(
        netease_search=netease_search,
        qq_search=qq_search,
        netease_preview=CrossPreview(),
        qq_preview=CrossPreview("https://qqmusic.qq.com/preview.m4a", "medium"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "qqmusic.qq.com":
            return audio(request)
        return httpx.Response(404)

    async with client_for(registry, [], handler) as client:
        response = await client.get(
            "/api/v1/preview/origin/origin-1/stream",
            params={"title": QQ.title, "artist": QQ.artist, "duration_ms": "320000"},
        )
    assert response.status_code == 200
    assert probe.order == ["qqmusic"]
    assert netease_search.calls == []
    assert events[0].source_platform == "qqmusic"


async def test_searches_never_run_at_the_same_time() -> None:
    probe = Probe()
    netease_search = CrossSearch([candidate("netease", duration_ms=210_000)], probe=probe)
    qq_search = CrossSearch(
        [candidate("qqmusic", duration_ms=210_000)],
        platform="qqmusic",
        probe=probe,
    )
    registry = two_platform_registry(
        netease_search=netease_search,
        qq_search=qq_search,
        netease_preview=CrossPreview(),
        qq_preview=CrossPreview(),
    )
    origin = QQ.model_copy(update={"platform": "origin"})
    planner = PreviewPlanner(origin, registry, PreviewPolicy())
    assert await drain(planner) == []
    assert probe.order == ["netease", "qqmusic"]
    assert probe.peak == 1


async def test_a_recent_failure_is_not_searched_again() -> None:
    search = CrossSearch([candidate("netease", duration_ms=210_000)])
    official = CrossPreview()
    async with client_for(registry_with(search, official), [], music_163_only) as client:
        first = await client.get(ENDPOINT, params=PARAMS)
        second = await client.get(ENDPOINT, params=PARAMS)
    assert first.status_code == second.status_code == 404
    assert len(search.calls) == 1


async def test_a_platform_that_never_plays_is_demoted() -> None:
    search = CrossSearch([candidate("netease", duration_ms=210_000)])
    async with client_for(registry_with(search, CrossPreview()), [], music_163_only) as client:
        # Distinct songs so the negative cache cannot hide the later attempts.
        for index in range(3):
            response = await client.get(
                f"/api/v1/preview/qqmusic/song-{index}/stream", params=PARAMS
            )
            assert response.status_code == 404
    # Beta posterior after three failures: (0 + 1) / (3 + 2), below the 0.5 prior.
    assert preview_telemetry.RATES.rate(QQ.platform, "netease") < 0.5


async def test_a_failed_borrow_is_recorded_for_the_next_ranking(
    events: list[preview_telemetry.PreviewEvent],
) -> None:
    search = CrossSearch([candidate("netease", duration_ms=210_000)])
    async with client_for(registry_with(search, CrossPreview()), [], music_163_only) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 404
    failure = events[0]
    assert (failure.tier, failure.status, failure.source_platform) == ("T2", "error", "netease")
    assert failure.error == "cross_platform_unavailable"


async def test_a_working_source_is_reused_without_searching_again() -> None:
    search = CrossSearch([candidate("netease")])
    official = CrossPreview()
    async with client_for(registry_with(search, official), [], music_163_only) as client:
        first = await client.get(ENDPOINT, params=PARAMS)
        second = await client.get(ENDPOINT, params=PARAMS)
    assert first.status_code == second.status_code == 200
    assert len(search.calls) == 1
    assert official.calls == ["287398"]


async def test_a_cache_hit_does_not_vote_in_the_rate_store_again() -> None:
    search = CrossSearch([candidate("netease")])
    official = CrossPreview()
    async with client_for(registry_with(search, official), [], music_163_only) as client:
        first = await client.get(ENDPOINT, params=PARAMS)
        second = await client.get(ENDPOINT, params=PARAMS)
    assert first.status_code == second.status_code == 200
    assert len(search.calls) == 1
    # One upstream success, one sample: replaying the cached decision must not
    # let a single resolved URL keep raising the pair's playability.
    counts = preview_telemetry.RATES._pairs[("qqmusic", "netease")]
    assert (counts.success, counts.failure) == (1, 0)


async def test_a_cache_hit_is_logged_without_becoming_a_new_event(
    events: list[preview_telemetry.PreviewEvent],
) -> None:
    search = CrossSearch([candidate("netease")])
    official = CrossPreview()
    async with client_for(registry_with(search, official), [], music_163_only) as client:
        await client.get(ENDPOINT, params=PARAMS)
        await client.get(ENDPOINT, params=PARAMS)
    assert [(event.tier, event.cached) for event in events] == [("T2", False), ("T2", True)]


async def test_a_cached_url_that_stops_opening_is_dropped_and_searched_again() -> None:
    search = CrossSearch([candidate("netease")])
    official = CrossPreview()
    key = preview_telemetry.cache_key(QQ)

    def handler(request: httpx.Request) -> httpx.Response:
        if "expired" in str(request.url):
            return httpx.Response(403)
        return audio(request)

    async with client_for(registry_with(search, official), [], handler) as client:
        assert (await client.get(ENDPOINT, params=PARAMS)).status_code == 200
        # Same decision, dead address: what an expired signed URL looks like.
        preview_telemetry.CACHE.store_positive(
            key,
            preview_telemetry.CachedTarget(
                platform="netease",
                external_id="287398",
                url="https://music.163.com/song/media/outer/url?id=expired.mp3",
                match_score=1.0,
            ),
            ttl_sec=600.0,
        )
        second = await client.get(ENDPOINT, params=PARAMS)
        stored = preview_telemetry.CACHE.positive(key)

    assert second.status_code == 200
    assert len(search.calls) == 2
    assert stored is not None and stored.url == OUTER_URL


async def test_download_only_skips_official_and_cross_platform_tiers() -> None:
    search = CrossSearch([candidate("netease")])
    official = CrossPreview()
    source = Source("backup")
    async with client_for(
        registry_with(search, official), [source_record(source)], audio
    ) as client:
        response = await client.get(ENDPOINT, params=PARAMS | {"download_only": "true"})
    assert response.status_code == 200
    assert search.calls == []
    assert official.calls == []
    assert source.resolved == 1


async def test_a_slow_platform_is_abandoned_at_the_deadline_and_download_sources_run(
    events: list[preview_telemetry.PreviewEvent],
) -> None:
    search = CrossSearch([candidate("netease")], delay_sec=5)
    official = CrossPreview()
    source = Source("backup")
    settings = SimpleNamespace(
        preview_cross_platform=True,
        preview_match_min_score=0.94,
        preview_max_candidates=2,
        preview_deadline_sec=0.2,
        preview_negative_ttl_sec=180.0,
        preview_positive_ttl_sec=600.0,
    )
    async with client_for(
        registry_with(search, official), [source_record(source)], audio, settings=settings
    ) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert official.calls == []
    assert source.resolved == 1
    assert [event.tier for event in events] == ["T3"]


async def test_a_deadline_is_not_remembered_as_unplayable(
    events: list[preview_telemetry.PreviewEvent],
) -> None:
    search = CrossSearch([candidate("netease")])
    slow = SlowPreview(0.3)
    settings = SimpleNamespace(
        preview_cross_platform=True,
        preview_match_min_score=0.94,
        preview_max_candidates=2,
        preview_deadline_sec=0.05,
        preview_negative_ttl_sec=180.0,
        preview_positive_ttl_sec=600.0,
    )
    async with client_for(
        registry_with(search, slow), [], music_163_only, settings=settings
    ) as client:
        first = await client.get(ENDPOINT, params=PARAMS)
        second = await client.get(ENDPOINT, params=PARAMS)
    assert first.status_code == second.status_code == 404
    # Running out of budget proves nothing about the song, so the next click must
    # be allowed to search again instead of being quarantined for three minutes.
    assert len(search.calls) == 2
    assert preview_telemetry.CACHE.negative(preview_telemetry.cache_key(QQ)) is False
    assert [event.error for event in events if event.tier == "T2"] == [
        "cross_platform_deadline_exceeded",
        "cross_platform_deadline_exceeded",
    ]


async def test_a_slow_search_is_not_cut_by_a_per_call_timeout() -> None:
    search = CrossSearch([candidate("netease")], delay_sec=0.3)
    official = CrossPreview()
    # A stale per-call knob must not clip a search any more: only the overall
    # cross-platform budget is allowed to end an attempt early.
    settings = SimpleNamespace(
        preview_cross_platform=True,
        preview_match_min_score=0.94,
        preview_max_candidates=2,
        preview_search_timeout_sec=0.001,
        preview_deadline_sec=30.0,
        preview_negative_ttl_sec=180.0,
        preview_positive_ttl_sec=600.0,
    )
    async with client_for(
        registry_with(search, official), [], music_163_only, settings=settings
    ) as client:
        response = await client.get(ENDPOINT, params=PARAMS)
    assert response.status_code == 200
    assert official.calls == ["287398"]


async def test_search_that_finds_nothing_is_still_reported_as_searched() -> None:
    registry = registry_with(CrossSearch([]), CrossPreview())
    planner = PreviewPlanner(QQ, registry, PreviewPolicy())
    assert await drain(planner) == []
    assert planner.searched is True
    assert planner.attempted is False


async def test_cross_platform_can_be_switched_off() -> None:
    registry = registry_with(CrossSearch([candidate("netease")]), CrossPreview())
    planner = PreviewPlanner(QQ, registry, PreviewPolicy(cross_platform=False))
    assert planner.platforms == []
    assert await drain(planner) == []


async def test_platform_order_prefers_history_and_breaks_ties_by_id() -> None:
    registry = two_platform_registry(
        netease_search=CrossSearch([]),
        qq_search=CrossSearch([], platform="qqmusic"),
        netease_preview=CrossPreview(),
        qq_preview=CrossPreview(),
    )
    origin = QQ.model_copy(update={"platform": "origin"})
    cold = PreviewPlanner(origin, registry, PreviewPolicy())
    assert cold.platforms == ["netease", "qqmusic"]

    for _ in range(5):
        preview_telemetry.RATES.record("origin", "netease", False)
        preview_telemetry.RATES.record("origin", "qqmusic", True)
    warm = PreviewPlanner(origin, registry, PreviewPolicy())
    assert warm.platforms == ["qqmusic", "netease"]


def test_version_markers_only_flag_real_variants() -> None:
    assert version_markers("我不难过 (Live)") == frozenset({"live"})
    assert version_markers("我不难过（伴奏）") == frozenset({"伴奏"})
    assert version_markers("Deliverance") == frozenset()
    assert version_markers("我不难过") == frozenset()


def test_isrc_match_skips_the_text_guards() -> None:
    origin = QQ.model_copy(update={"isrc": "CNA231200001"})
    other = candidate("netease").model_copy(
        update={"title": "我不难过 (Live)", "isrc": "cna231200001"}
    )
    assert is_cross_platform_match(origin, other, min_score=0.94) is True

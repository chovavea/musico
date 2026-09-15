from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from app.adapters.http.routes import build_router
from app.adapters.persistence.library_repository import LibraryRepository, _fallback_event_payload
from app.adapters.persistence.models import DownloadTaskRow, FallbackEventRow, LibraryTrackRow
from app.domain.models import TrackRef
from app.fallback.service import FallbackService
from app.fallback.sonoma import FallbackLink, SonomaFallback, _quark_share_url, _song_hits
from app.settings import Settings
from fastapi import FastAPI
from starlette.testclient import TestClient

BASE_URL = "https://mirror.example"
SEARCH_URL = f"{BASE_URL}/index/search/?keyword=%E7%A8%BB%E9%A6%99"

SEARCH_HTML = """
<ul>
  <li>
    <article>
      <a href="/song/zhoujielun-dao-xiang.html" rel="bookmark"  title="周杰伦_《稻香》MP3下载" >
      <h3><img src="/resource/images/yf.jpg" class="w14 mr-10" alt="音乐图标">稻香-周杰伦</h3>
      <p><small>
        <span class="tagstyle2 f-10 f-nob">WAV</span>
        <span class="tagstyle4 f-10 f-nob">37.59 MB</span>
      </small></p>
      </a>
    </article>
  </li>
</ul>
<div class="right fr">
  <li><a href="/song/eqktjacvrz.html" rel="bookmark" class="yanse"
      title="冷漠《红尘》MP3高品质下载">红尘-冷漠</a></li>
</div>
"""

SONG_HTML = """
<div class="info-zi mb15" id="myarticle">
  <a href="/dls/rwk192651.html"  rel="nofollow" title="稻香 周杰伦WAV"  target="_blank">
    <h3 class="title">WAV无损音质</h3>
  </a>
</div>
<h4>大小： 37.59 MB</h4>
"""

SONG_HTML_MP3_ONLY = """
<a href="/dls/rmk192651.html"  rel="nofollow" title="稻香 周杰伦mp3音质"  target="_blank">
  <h3 class="title">MP3音质</h3>
</a>
"""

HANDOFF_HTML = "<script>window.location.href='https://pan.quark.cn/s/ef20d65b3f5e';</script>"
HANDOFF_HTML_EVIL = (
    "<script>window.location.href='https://evil.example/pan.quark.cn/s/ef20d65b3f5e';</script>"
)
SONG_HTML_ALT = SONG_HTML.replace("rwk192651", "rwk192652")
TWO_HIT_SEARCH_HTML = """
<ul>
  <li>
    <article>
      <a href="/song/zhoujielun-dao-xiang.html" rel="bookmark"  title="周杰伦_《稻香》MP3下载" >
      <h3>稻香-周杰伦</h3>
      <p><small>
        <span class="tagstyle2 f-10 f-nob">WAV</span>
      </small></p>
      </a>
    </article>
  </li>
  <li>
    <article>
      <a href="/song/dao-xiang-alt.html" rel="bookmark"  title="周杰伦_《稻香》MP3下载" >
      <h3>稻香-周杰伦</h3>
      <p><small>
        <span class="tagstyle2 f-10 f-nob">WAV</span>
      </small></p>
      </a>
    </article>
  </li>
</ul>
"""


async def _offline_guard(_url: str, _hosts: object) -> None:
    """Every request is served by MockTransport, so skip the real DNS guard."""
    return None


def _track(title: str = "稻香", artist: str = "周杰伦") -> TrackRef:
    return TrackRef(platform="library", external_id="track-1", title=title, artist=artist)


async def _resolve_with(
    handler: Any, track: TrackRef | None = None
) -> FallbackLink:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fallback = SonomaFallback(client, BASE_URL, url_guard=_offline_guard)
        return await fallback.resolve(track or _track())


def test_search_parser_ignores_links_without_a_result_heading() -> None:
    hits = _song_hits(SEARCH_HTML)
    assert [hit.path for hit in hits] == ["/song/zhoujielun-dao-xiang.html"]
    assert hits[0].title == "稻香"
    assert hits[0].artist == "周杰伦"
    assert hits[0].label == "WAV"


@pytest.mark.asyncio
async def test_fallback_follows_the_wav_route_to_the_quark_share() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/index/search/":
            return httpx.Response(200, text=SEARCH_HTML)
        if request.url.path == "/song/zhoujielun-dao-xiang.html":
            return httpx.Response(200, text=SONG_HTML)
        if request.url.path == "/dls/rwk192651.html":
            return httpx.Response(200, text=HANDOFF_HTML)
        return httpx.Response(404, text="missing")

    link = await _resolve_with(handler)

    assert seen == [
        SEARCH_URL,
        f"{BASE_URL}/song/zhoujielun-dao-xiang.html",
        f"{BASE_URL}/dls/rwk192651.html",
    ]
    assert link.outcome == "jumped"
    assert link.share_url == "https://pan.quark.cn/s/ef20d65b3f5e"
    assert link.page_url == f"{BASE_URL}/song/zhoujielun-dao-xiang.html"
    assert link.detail == "WAV · 37.59 MB"


@pytest.mark.asyncio
async def test_fallback_reports_no_wav_when_only_mp3_exists() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/index/search/":
            return httpx.Response(200, text=SEARCH_HTML)
        return httpx.Response(200, text=SONG_HTML_MP3_ONLY)

    link = await _resolve_with(handler)

    assert link.outcome == "no_wav"
    assert link.share_url is None
    assert link.detail == "站点只有 MP3 版本"


@pytest.mark.asyncio
async def test_fallback_reports_not_found_when_the_site_has_no_match() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SEARCH_HTML)

    link = await _resolve_with(handler, _track(title="晴天", artist="周杰伦"))

    assert link.outcome == "not_found"


@pytest.mark.asyncio
async def test_fallback_reports_unreachable_when_the_site_errors() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="maintenance")

    link = await _resolve_with(handler)

    assert link.outcome == "unreachable"
    assert link.error is not None and "503" in link.error


@pytest.mark.asyncio
async def test_fallback_reports_missing_share_link_when_handoff_has_no_quark_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/index/search/":
            return httpx.Response(200, text=SEARCH_HTML)
        if request.url.path == "/song/zhoujielun-dao-xiang.html":
            return httpx.Response(200, text=SONG_HTML)
        return httpx.Response(200, text="<html>维护中</html>")

    link = await _resolve_with(handler)

    assert link.outcome == "no_share_link"
    assert link.page_url == f"{BASE_URL}/song/zhoujielun-dao-xiang.html"


def test_share_parser_rejects_quark_host_smuggled_inside_another_origin() -> None:
    assert _quark_share_url(HANDOFF_HTML) == "https://pan.quark.cn/s/ef20d65b3f5e"
    assert _quark_share_url(HANDOFF_HTML_EVIL) is None
    assert (
        _quark_share_url("see https://evil.example/?next=https://pan.quark.cn/s/ef20d65b3f5e")
        == "https://pan.quark.cn/s/ef20d65b3f5e"
    )


@pytest.mark.asyncio
async def test_fallback_ignores_a_smuggled_quark_host_in_the_handoff_page() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/index/search/":
            return httpx.Response(200, text=SEARCH_HTML)
        if request.url.path == "/song/zhoujielun-dao-xiang.html":
            return httpx.Response(200, text=SONG_HTML)
        return httpx.Response(200, text=HANDOFF_HTML_EVIL)

    link = await _resolve_with(handler)

    assert link.outcome == "no_share_link"
    assert link.share_url is None


@pytest.mark.asyncio
async def test_fallback_tries_the_next_candidate_when_the_first_song_page_errors() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/index/search/":
            return httpx.Response(200, text=TWO_HIT_SEARCH_HTML)
        if request.url.path == "/song/zhoujielun-dao-xiang.html":
            return httpx.Response(404, text="gone")
        if request.url.path == "/song/dao-xiang-alt.html":
            return httpx.Response(200, text=SONG_HTML_ALT)
        if request.url.path == "/dls/rwk192652.html":
            return httpx.Response(200, text=HANDOFF_HTML)
        return httpx.Response(404, text="missing")

    link = await _resolve_with(handler)

    assert "/song/zhoujielun-dao-xiang.html" in seen
    assert "/song/dao-xiang-alt.html" in seen
    assert link.outcome == "jumped"
    assert link.share_url == "https://pan.quark.cn/s/ef20d65b3f5e"
    assert link.page_url == f"{BASE_URL}/song/dao-xiang-alt.html"


@pytest.mark.asyncio
async def test_fallback_tries_the_next_candidate_when_the_first_handoff_has_no_share() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/index/search/":
            return httpx.Response(200, text=TWO_HIT_SEARCH_HTML)
        if request.url.path == "/song/zhoujielun-dao-xiang.html":
            return httpx.Response(200, text=SONG_HTML)
        if request.url.path == "/dls/rwk192651.html":
            return httpx.Response(200, text="<html>维护中</html>")
        if request.url.path == "/song/dao-xiang-alt.html":
            return httpx.Response(200, text=SONG_HTML_ALT)
        if request.url.path == "/dls/rwk192652.html":
            return httpx.Response(200, text=HANDOFF_HTML)
        return httpx.Response(404, text="missing")

    link = await _resolve_with(handler)

    assert link.outcome == "jumped"
    assert link.page_url == f"{BASE_URL}/song/dao-xiang-alt.html"


class _Session:
    """Minimal stand-in for AsyncSession: the repository only gets/adds/commits."""

    def __init__(self, task: Any, track: Any) -> None:
        self.task = task
        self.track = track
        self.added: list[Any] = []
        self.commits = 0

    async def get(self, model: Any, _key: Any) -> Any:
        return self.task if model is DownloadTaskRow else self.track

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Resolver:
    def __init__(self, link: FallbackLink) -> None:
        self.link = link
        self.calls = 0

    async def resolve(self, _track: TrackRef) -> FallbackLink:
        self.calls += 1
        return self.link


@pytest.mark.asyncio
async def test_service_resolves_a_failed_task_once_and_serves_the_cache_afterwards() -> None:
    task = DownloadTaskRow(id="task-1", library_track_id="track-1", status="failed")
    session = _Session(task, LibraryTrackRow(id="track-1", title="稻香", artist="周杰伦"))
    resolver = _Resolver(
        FallbackLink(outcome="jumped", share_url="https://pan.quark.cn/s/abc123")
    )
    async with httpx.AsyncClient() as client:
        service = FallbackService(
            lambda: session,  # type: ignore[arg-type]
            client,
            Settings(fallback_base_url=""),
            resolver=resolver,
        )
        first = await service.resolve_task("task-1")
        second = await service.resolve_task("task-1")

    assert first is not None
    assert first["outcome"] == "jumped"
    assert first["url"] == "https://pan.quark.cn/s/abc123"
    assert first.get("cached") is None
    assert second is not None and second.get("cached") is True
    assert resolver.calls == 1
    assert session.commits == 1
    assert len(session.added) == 1
    event = session.added[0]
    assert (event.trigger, event.outcome) == ("fallback_request", "jumped")
    assert event.task_id == "task-1"
    assert event.track_id == "track-1"
    assert event.share_url == "https://pan.quark.cn/s/abc123"


@pytest.mark.asyncio
async def test_service_never_resolves_a_task_that_did_not_fail() -> None:
    task = DownloadTaskRow(id="task-2", library_track_id="track-2", status="downloading")
    session = _Session(task, LibraryTrackRow(id="track-2", title="稻香", artist="周杰伦"))
    resolver = _Resolver(FallbackLink(outcome="jumped", share_url="https://pan.quark.cn/s/x"))
    async with httpx.AsyncClient() as client:
        service = FallbackService(
            lambda: session,  # type: ignore[arg-type]
            client,
            Settings(fallback_base_url=""),
            resolver=resolver,
        )
        result = await service.resolve_task("task-2")

    assert result is not None
    assert result["outcome"] == "not_failed"
    assert resolver.calls == 0
    assert session.added == []


@pytest.mark.asyncio
async def test_service_is_disabled_without_a_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MUSICO_FALLBACK_BASE_URL", raising=False)
    async with httpx.AsyncClient() as client:
        assert FallbackService(lambda: None, client, Settings()).enabled is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_service_is_enabled_when_a_base_url_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MUSICO_FALLBACK_BASE_URL", f"{BASE_URL}/ignored/path")
    async with httpx.AsyncClient() as client:
        service = FallbackService(lambda: None, client, Settings())  # type: ignore[arg-type]
    assert service.enabled is True


@pytest.mark.asyncio
async def test_service_is_disabled_when_base_url_is_not_an_http_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MUSICO_FALLBACK_BASE_URL", "not-a-url")
    async with httpx.AsyncClient() as client:
        assert FallbackService(lambda: None, client, Settings()).enabled is False  # type: ignore[arg-type]


class _EmptyResult:
    def scalars(self) -> _EmptyResult:
        return self

    def all(self) -> list[Any]:
        return []


class _EmptySession:
    """Chart health reads two empty result sets; nothing else is touched."""

    async def execute(self, *_args: object, **_kwargs: object) -> _EmptyResult:
        return _EmptyResult()

    async def __aenter__(self) -> _EmptySession:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _api_client(state: dict[str, Any]) -> TestClient:
    app = FastAPI()
    app.include_router(build_router())
    for key, value in state.items():
        setattr(app.state, key, value)
    return TestClient(app)


def test_fallback_endpoint_returns_the_share_link_for_a_failed_task() -> None:
    class _Service:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def resolve_task(self, task_id: str) -> dict[str, Any]:
            self.calls.append(task_id)
            return {
                "task_id": task_id,
                "source_id": "sonoma",
                "source_name": "Sonoma",
                "outcome": "jumped",
                "url": "https://pan.quark.cn/s/abc123",
                "page_url": "https://mirror.example/song/x.html",
                "detail": "WAV",
                "error": None,
                "title": "稻香",
                "artist": "周杰伦",
            }

    service = _Service()
    with _api_client({"fallback_service": service}) as client:
        response = client.post("/api/v1/downloads/task-1/fallback")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["outcome"] == "jumped"
    assert body["data"]["url"] == "https://pan.quark.cn/s/abc123"
    assert service.calls == ["task-1"]


def test_fallback_endpoint_reports_an_unknown_task() -> None:
    class _Service:
        async def resolve_task(self, _task_id: str) -> None:
            return None

    with _api_client({"fallback_service": _Service()}) as client:
        response = client.post("/api/v1/downloads/missing/fallback")

    assert response.status_code == 404


def test_health_reports_the_fallback_without_moving_status() -> None:
    class _Service:
        async def health(self, limit: int) -> dict[str, Any]:
            assert limit == 20
            return {
                "enabled": True,
                "source_id": "sonoma",
                "source_name": "Sonoma",
                "counts": {},
                "download_failed_total": 0,
                "last_success_at": None,
                "last_failure_at": None,
                "consecutive_failures": 0,
                "events": [],
            }

    state = {
        "session_factory": _EmptySession,
        "board_specs": [],
        "settings": Settings(),
        "fallback_service": _Service(),
    }
    with _api_client(state) as client:
        body = client.get("/api/v1/health").json()

    assert body["code"] == 0
    assert body["data"]["status"] == "ready"
    assert body["data"]["fallback"]["source_name"] == "Sonoma"


def _event(
    *,
    event_id: str,
    trigger: str,
    outcome: str,
    created_at: str,
    share_url: str | None = None,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "task_id": event_id,
        "track_id": "track-1",
        "title": "稻香",
        "artist": "周杰伦",
        "source_id": "sonoma",
        "trigger": trigger,
        "outcome": outcome,
        "detail": None,
        "share_url": share_url,
        "page_url": None,
        "created_at": created_at,
    }


def test_health_event_payload_omits_share_url() -> None:
    row = FallbackEventRow(
        id="evt-1",
        title="稻香",
        artist="周杰伦",
        trigger="fallback_request",
        outcome="jumped",
        share_url="https://pan.quark.cn/s/secret",
        created_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    assert _fallback_event_payload(row)["share_url"] is None
    assert (
        _fallback_event_payload(row, include_share_url=True)["share_url"]
        == "https://pan.quark.cn/s/secret"
    )


@pytest.mark.asyncio
async def test_health_scores_fallback_requests_even_when_download_failures_fill_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, str | None, bool]] = []

    async def fake_list(
        self: LibraryRepository,
        limit: int = 20,
        *,
        trigger: str | None = None,
        include_share_url: bool = False,
    ) -> list[dict[str, Any]]:
        calls.append((limit, trigger, include_share_url))
        if trigger == "fallback_request":
            return [
                _event(
                    event_id="fb-2",
                    trigger="fallback_request",
                    outcome="unreachable",
                    created_at="2026-09-15T02:00:00+00:00",
                ),
                _event(
                    event_id="fb-1",
                    trigger="fallback_request",
                    outcome="jumped",
                    created_at="2026-09-15T01:00:00+00:00",
                ),
            ]
        return [
            _event(
                event_id="dl-1",
                trigger="download_failed",
                outcome="failed",
                created_at="2026-09-15T03:00:00+00:00",
            )
        ]

    async def fake_counts(self: LibraryRepository) -> dict[str, int]:
        return {
            "download_failed:failed": 20,
            "fallback_request:unreachable": 1,
            "fallback_request:jumped": 1,
        }

    monkeypatch.setattr(LibraryRepository, "list_fallback_events", fake_list)
    monkeypatch.setattr(LibraryRepository, "fallback_event_counts", fake_counts)

    async with httpx.AsyncClient() as client:
        service = FallbackService(
            lambda: _EmptySession(),  # type: ignore[arg-type]
            client,
            Settings(fallback_base_url=""),
            resolver=_Resolver(FallbackLink(outcome="jumped")),
        )
        payload = await service.health(20)

    assert payload["consecutive_failures"] == 1
    assert payload["last_failure_at"] == "2026-09-15T02:00:00+00:00"
    assert payload["last_success_at"] == "2026-09-15T01:00:00+00:00"
    assert payload["download_failed_total"] == 20
    assert [event["id"] for event in payload["events"]] == ["dl-1"]
    assert calls == [(20, None, False), (20, "fallback_request", False)]
    assert all(event.get("share_url") is None for event in payload["events"])

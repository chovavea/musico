from __future__ import annotations

import hashlib
import io
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from app.adapters.download_worker import DownloadWorker, _headers_for_cross_origin_redirect
from app.adapters.persistence.models import DownloadTaskRow
from app.domain.models import AudioQuality, DownloadCandidate, DownloadResponse, TrackRef
from app.download_sources.registry import DownloadSourceRecord, DownloadSourceRegistry
from app.settings import Settings


async def _allow_all_urls(_url: str, _hosts: object) -> None:
    return None


class _Source:
    def __init__(self, candidates: list[DownloadCandidate]) -> None:
        self.candidates = candidates

    async def search(self, _track: TrackRef) -> list[DownloadCandidate]:
        return self.candidates

    async def resolve(self, _candidate: DownloadCandidate, *, offset: int = 0) -> DownloadResponse:
        return DownloadResponse(url="https://media.example/audio.wav", headers={})


class _RecordingSource(_Source):
    def __init__(self, label: str, calls: list[str]) -> None:
        super().__init__([])
        self.label = label
        self.calls = calls

    async def search(self, _track: TrackRef) -> list[DownloadCandidate]:
        self.calls.append(self.label)
        return []


class _Repo:
    def __init__(self) -> None:
        self.saved: list[DownloadCandidate] = []
        self.commits = 0

    async def save_candidate_snapshot(
        self,
        _task: DownloadTaskRow,
        candidates: list[DownloadCandidate],
        _selected: DownloadCandidate,
    ) -> bool:
        self.saved = candidates
        return True

    async def heartbeat(
        self, task: DownloadTaskRow, bytes_done: int, bytes_total: int | None
    ) -> bool:
        task.bytes_done = bytes_done
        task.bytes_total = bytes_total
        return True

    async def commit(self) -> None:
        self.commits += 1


class _Session:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_candidate_search_uses_configured_source_priority_order() -> None:
    calls: list[str] = []
    high_quality_source = _RecordingSource("high", calls)
    lower_quality_source = _RecordingSource("low", calls)
    registry = DownloadSourceRegistry(
        sources={
            "low": DownloadSourceRecord(
                source_id="low",
                name="low",
                priority=90,
                hosts=("low.example",),
                config_schema={},
                source=lower_quality_source,
            ),
            "high": DownloadSourceRecord(
                source_id="high",
                name="high",
                priority=100,
                hosts=("high.example",),
                config_schema={},
                source=high_quality_source,
            ),
        }
    )
    settings = Settings(boards_yaml=Path("configs/boards.yaml"))
    worker = DownloadWorker(
        SimpleNamespace(), httpx.AsyncClient(), registry, settings, url_guard=_allow_all_urls
    )
    selected = await worker._candidate_pool(
        _Session(),
        _Repo(),
        DownloadTaskRow(id="task", library_track_id="track", status="downloading"),
        TrackRef(platform="qqmusic", external_id="1", title="晴天", artist="周杰伦"),
    )
    await worker._client.aclose()
    assert selected == []
    assert calls == ["high", "low"]


@pytest.mark.asyncio
async def test_candidate_pool_keeps_allowed_qualities_for_downgrade() -> None:
    track = TrackRef(platform="qqmusic", external_id="1", title="晴天", artist="周杰伦")
    candidates = [
        DownloadCandidate(
            source_id="aries",
            source_track_id="hires",
            title="晴天",
            artist="周杰伦",
            quality=AudioQuality(format="flac", sample_rate_hz=96_000, bit_depth=24),
        ),
        DownloadCandidate(
            source_id="aries",
            source_track_id="cd",
            title="晴天",
            artist="周杰伦",
            quality=AudioQuality(format="flac", sample_rate_hz=44_100, bit_depth=16),
        ),
        DownloadCandidate(
            source_id="aries",
            source_track_id="mp3",
            title="晴天",
            artist="周杰伦",
            quality=AudioQuality(format="mp3"),
        ),
        DownloadCandidate(
            source_id="aries",
            source_track_id="dff",
            title="晴天",
            artist="周杰伦",
            quality=AudioQuality(format="dff"),
        ),
        DownloadCandidate(
            source_id="aries",
            source_track_id="dsf",
            title="晴天",
            artist="周杰伦",
            quality=AudioQuality(format="dsf"),
        ),
        DownloadCandidate(
            source_id="aries",
            source_track_id="wav",
            title="晴天",
            artist="周杰伦",
            quality=AudioQuality(format="wav"),
        ),
    ]
    source = _Source(candidates)
    registry = DownloadSourceRegistry(
        sources={
            "aries": DownloadSourceRecord(
                source_id="aries",
                name="aries",
                priority=100,
                hosts=("media.example",),
                config_schema={},
                source=source,
            )
        }
    )
    settings = Settings(boards_yaml=Path("configs/boards.yaml"))
    worker = DownloadWorker(
        SimpleNamespace(), httpx.AsyncClient(), registry, settings, url_guard=_allow_all_urls
    )
    repo = _Repo()
    task = DownloadTaskRow(id="task", library_track_id="track", status="downloading")
    selected = await worker._candidate_pool(_Session(), repo, task, track)
    await worker._client.aclose()
    assert [item.source_track_id for item in selected] == ["dsf", "hires", "cd", "wav"]
    assert [item.source_track_id for item in repo.saved] == ["dsf", "hires", "cd", "wav"]


@pytest.mark.asyncio
async def test_candidate_pool_does_not_downgrade_requested_quality() -> None:
    track = TrackRef(platform="qqmusic", external_id="1", title="晴天", artist="周杰伦")
    candidates = [
        DownloadCandidate(
            source_id="aries",
            source_track_id="hires",
            title="晴天",
            artist="周杰伦",
            quality=AudioQuality(format="flac", sample_rate_hz=96_000, bit_depth=24),
        ),
        DownloadCandidate(
            source_id="aries",
            source_track_id="cd",
            title="晴天",
            artist="周杰伦",
            quality=AudioQuality(format="flac", sample_rate_hz=44_100, bit_depth=16),
        ),
    ]
    source = _Source(candidates)
    registry = DownloadSourceRegistry(
        sources={
            "aries": DownloadSourceRecord(
                source_id="aries",
                name="aries",
                priority=100,
                hosts=("media.example",),
                config_schema={},
                source=source,
            )
        }
    )
    settings = Settings(boards_yaml=Path("configs/boards.yaml"))
    worker = DownloadWorker(
        SimpleNamespace(), httpx.AsyncClient(), registry, settings, url_guard=_allow_all_urls
    )
    repo = _Repo()
    task = DownloadTaskRow(
        id="task",
        library_track_id="track",
        status="downloading",
        requested_quality={"format": "flac", "sample_rate_hz": 44_100, "bit_depth": 16},
    )
    selected = await worker._candidate_pool(_Session(), repo, task, track)
    await worker._client.aclose()
    assert [item.source_track_id for item in selected] == ["cd"]


def test_cross_origin_redirect_drops_sensitive_headers() -> None:
    headers = {
        "Authorization": "Bearer <REDACTED>",
        "X-Api-Key": "<REDACTED>",
        "Cookie": "session=<REDACTED>",
        "Proxy-Authorization": "Basic <REDACTED>",
        "Host": "source.example",
        "Range": "bytes=10-",
        "Referer": "https://source.example/page",
    }
    redirected = _headers_for_cross_origin_redirect(
        headers,
        "https://source.example/audio.flac",
        "https://cdn.example/audio.flac",
    )
    assert redirected == {
        "Range": "bytes=10-",
        "Referer": "https://source.example/page",
    }


@pytest.mark.asyncio
async def test_download_writes_and_verifies_audio(tmp_path: Path) -> None:
    audio = io.BytesIO()
    with wave.open(audio, "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(44_100)
        stream.writeframes(b"\0\0" * 2 * 100)
    payload = audio.getvalue()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"content-type": "audio/wav"})

    source = _Source([])
    registry = DownloadSourceRegistry(
        sources={
            "aries": DownloadSourceRecord(
                source_id="aries",
                name="aries",
                priority=100,
                hosts=("media.example",),
                config_schema={},
                source=source,
            )
        }
    )
    settings = Settings(boards_yaml=Path("configs/boards.yaml"), music_library_dir=tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    worker = DownloadWorker(
        SimpleNamespace(), client, registry, settings, url_guard=_allow_all_urls
    )
    repo = _Repo()
    task = DownloadTaskRow(id="task", library_track_id="track", status="downloading")
    candidate = DownloadCandidate(
        source_id="aries",
        source_track_id="wav",
        title="晴天",
        artist="周杰伦",
        quality=AudioQuality(format="wav"),
    )
    relative, size, digest = await worker._download(task, candidate, repo)
    await client.aclose()
    path = tmp_path / relative
    assert path.is_file()
    assert relative == "task.wav"
    assert not (tmp_path / "track").exists()
    assert size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()


@pytest.mark.asyncio
async def test_download_rejects_audio_that_does_not_match_advertised_quality(
    tmp_path: Path,
) -> None:
    audio = io.BytesIO()
    with wave.open(audio, "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(44_100)
        stream.writeframes(b"\0\0" * 2 * 100)
    payload = audio.getvalue()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"content-type": "audio/wav"})

    source = _Source([])
    registry = DownloadSourceRegistry(
        sources={
            "aries": DownloadSourceRecord(
                source_id="aries",
                name="aries",
                priority=100,
                hosts=("media.example",),
                config_schema={},
                source=source,
            )
        }
    )
    settings = Settings(boards_yaml=Path("configs/boards.yaml"), music_library_dir=tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    worker = DownloadWorker(
        SimpleNamespace(), client, registry, settings, url_guard=_allow_all_urls
    )
    repo = _Repo()
    task = DownloadTaskRow(id="task", library_track_id="track", status="downloading")
    candidate = DownloadCandidate(
        source_id="aries",
        source_track_id="wav",
        title="晴天",
        artist="周杰伦",
        quality=AudioQuality(format="wav", sample_rate_hz=96_000, bit_depth=24),
    )
    with pytest.raises(ValueError, match="advertised quality"):
        await worker._download(task, candidate, repo)
    await client.aclose()
    assert not (tmp_path / "task.part").exists()
    assert not (tmp_path / "task.wav").exists()


@pytest.mark.asyncio
async def test_download_rejects_audio_container_that_does_not_match_format(
    tmp_path: Path,
) -> None:
    audio = io.BytesIO()
    with wave.open(audio, "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(44_100)
        stream.writeframes(b"\0\0" * 2 * 100)
    payload = audio.getvalue()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"content-type": "audio/wav"})

    registry = _registry(
        _RedirectSource("https://media.example/audio.flac"), hosts=("media.example",)
    )
    settings = Settings(boards_yaml=Path("configs/boards.yaml"), music_library_dir=tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    worker = DownloadWorker(
        SimpleNamespace(), client, registry, settings, url_guard=_allow_all_urls
    )
    repo = _Repo()
    task = DownloadTaskRow(id="task", library_track_id="track", status="downloading")
    candidate = DownloadCandidate(
        source_id="aries",
        source_track_id="flac",
        title="晴天",
        artist="周杰伦",
        quality=AudioQuality(format="flac", sample_rate_hz=44_100, bit_depth=16),
    )
    with pytest.raises(ValueError, match="format"):
        await worker._download(task, candidate, repo)
    await client.aclose()
    assert not (tmp_path / "task.part").exists()
    assert not (tmp_path / "task.flac").exists()


@pytest.mark.asyncio
async def test_download_rejects_mp3_before_resolving_source(tmp_path: Path) -> None:
    registry = _registry(
        _RedirectSource("https://media.example/audio.mp3"), hosts=("media.example",)
    )
    settings = Settings(boards_yaml=Path("configs/boards.yaml"), music_library_dir=tmp_path)
    client = httpx.AsyncClient()
    worker = DownloadWorker(
        SimpleNamespace(), client, registry, settings, url_guard=_allow_all_urls
    )
    repo = _Repo()
    task = DownloadTaskRow(id="task", library_track_id="track", status="downloading")
    candidate = DownloadCandidate(
        source_id="aries",
        source_track_id="mp3",
        title="晴天",
        artist="周杰伦",
        quality=AudioQuality(format="mp3"),
    )
    with pytest.raises(ValueError, match="download format is not supported"):
        await worker._download(task, candidate, repo)
    await client.aclose()
    assert not (tmp_path / "task.part").exists()


async def _reject_everything(_url: str, _hosts: object) -> None:
    raise ValueError("outbound URL host is not allowed")


async def _reject_private(_url: str, _hosts: object) -> None:
    from app.adapters.http.safety import assert_outbound_url_allowed

    await assert_outbound_url_allowed(_url, _hosts)


@pytest.mark.asyncio
async def test_download_follows_safe_redirect(tmp_path: Path) -> None:
    audio = io.BytesIO()
    with wave.open(audio, "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(44_100)
        stream.writeframes(b"\0\0" * 2 * 100)
    payload = audio.getvalue()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/start.wav":
            return httpx.Response(
                302,
                headers={"location": "https://media.example/final.wav"},
            )
        return httpx.Response(200, content=payload, headers={"content-type": "audio/wav"})

    registry = _registry(
        _RedirectSource("https://media.example/start.wav"), hosts=("media.example",)
    )
    settings = Settings(boards_yaml=Path("configs/boards.yaml"), music_library_dir=tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    worker = DownloadWorker(
        SimpleNamespace(), client, registry, settings, url_guard=_allow_all_urls
    )
    repo = _Repo()
    task = DownloadTaskRow(id="task", library_track_id="track", status="downloading")
    candidate = _candidate(url="https://media.example/start.wav")
    relative, size, digest = await worker._download(task, candidate, repo)
    await client.aclose()
    assert calls == ["https://media.example/start.wav", "https://media.example/final.wav"]
    path = tmp_path / relative
    assert path.is_file()
    assert size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()


@pytest.mark.asyncio
async def test_download_rejects_redirect_to_private_host(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start.wav":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/evil.flac"})
        return httpx.Response(200, content=b"x")

    registry = _registry(_RedirectSource("https://1.1.1.1/start.wav"), hosts=("1.1.1.1",))
    settings = Settings(boards_yaml=Path("configs/boards.yaml"), music_library_dir=tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    worker = DownloadWorker(
        SimpleNamespace(), client, registry, settings, url_guard=_reject_private
    )
    repo = _Repo()
    task = DownloadTaskRow(id="task", library_track_id="track", status="downloading")
    candidate = _candidate(url="https://1.1.1.1/start.wav")
    with pytest.raises(ValueError, match="host is not allowed"):
        await worker._download(task, candidate, repo)
    await client.aclose()
    assert not (tmp_path / "task.part").exists()


@pytest.mark.asyncio
async def test_download_stops_after_redirect_limit(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://media.example/loop.wav"})

    registry = _registry(
        _RedirectSource("https://media.example/start.wav"), hosts=("media.example",)
    )
    settings = Settings(boards_yaml=Path("configs/boards.yaml"), music_library_dir=tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    worker = DownloadWorker(
        SimpleNamespace(), client, registry, settings, url_guard=_allow_all_urls
    )
    repo = _Repo()
    task = DownloadTaskRow(id="task", library_track_id="track", status="downloading")
    candidate = _candidate(url="https://media.example/loop.wav")
    with pytest.raises(ValueError, match="redirect limit"):
        await worker._download(task, candidate, repo)
    await client.aclose()


def _registry(source: _Source, hosts: tuple[str, ...]) -> DownloadSourceRegistry:
    return DownloadSourceRegistry(
        sources={
            "aries": DownloadSourceRecord(
                source_id="aries",
                name="aries",
                priority=100,
                hosts=hosts,
                config_schema={},
                source=source,
            )
        }
    )


def _candidate(url: str) -> DownloadCandidate:
    return DownloadCandidate(
        source_id="aries",
        source_track_id="wav",
        title="晴天",
        artist="周杰伦",
        quality=AudioQuality(format="wav"),
        locator={"download_url": url},
    )


class _RedirectSource:
    def __init__(self, url: str) -> None:
        self.url = url

    async def search(self, _track: TrackRef) -> list[DownloadCandidate]:
        return []

    async def resolve(self, _candidate: DownloadCandidate, *, offset: int = 0) -> DownloadResponse:
        return DownloadResponse(url=self.url, headers={})

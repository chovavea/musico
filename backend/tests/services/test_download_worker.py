from __future__ import annotations

import hashlib
import io
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.adapters.download_worker import DownloadWorker
from app.adapters.persistence.models import DownloadTaskRow
from app.download_sources.registry import DownloadSourceRecord, DownloadSourceRegistry
from app.domain.models import AudioQuality, DownloadCandidate, DownloadResponse, TrackRef
from app.settings import Settings


class _Source:
    def __init__(self, candidates: list[DownloadCandidate]) -> None:
        self.candidates = candidates

    async def search(self, _track: TrackRef) -> list[DownloadCandidate]:
        return self.candidates

    async def resolve(self, _candidate: DownloadCandidate, *, offset: int = 0) -> DownloadResponse:
        return DownloadResponse(url="https://example.invalid/audio.wav", headers={})


class _Repo:
    def __init__(self) -> None:
        self.saved: list[DownloadCandidate] = []
        self.commits = 0

    async def save_candidate_snapshot(
        self,
        _task: DownloadTaskRow,
        candidates: list[DownloadCandidate],
        _selected: DownloadCandidate,
    ) -> None:
        self.saved = candidates

    async def heartbeat(self, task: DownloadTaskRow, bytes_done: int, bytes_total: int | None) -> None:
        task.bytes_done = bytes_done
        task.bytes_total = bytes_total

    async def commit(self) -> None:
        self.commits += 1


class _Session:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_candidate_pool_keeps_only_highest_quality() -> None:
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
                hosts=("example.invalid",),
                config_schema={},
                source=source,
            )
        }
    )
    settings = Settings(boards_yaml=Path("configs/boards.yaml"))
    worker = DownloadWorker(SimpleNamespace(), httpx.AsyncClient(), registry, settings)
    repo = _Repo()
    task = DownloadTaskRow(id="task", library_track_id="track", status="downloading")
    selected = await worker._candidate_pool(_Session(), repo, task, track)
    await worker._client.aclose()
    assert [item.source_track_id for item in selected] == ["hires"]
    assert [item.source_track_id for item in repo.saved] == ["hires"]


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
                hosts=("example.invalid",),
                config_schema={},
                source=source,
            )
        }
    )
    settings = Settings(boards_yaml=Path("configs/boards.yaml"), music_library_dir=tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    worker = DownloadWorker(SimpleNamespace(), client, registry, settings)
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
    assert size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()

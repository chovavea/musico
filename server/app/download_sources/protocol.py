from __future__ import annotations

from typing import Protocol

import httpx

from app.domain.models import DownloadCandidate, DownloadResponse, TrackRef


class DownloadSourcePort(Protocol):
    async def search(self, track: TrackRef) -> list[DownloadCandidate]:
        ...

    async def resolve(
        self,
        candidate: DownloadCandidate,
        *,
        offset: int = 0,
    ) -> DownloadResponse:
        ...


class DownloadSourceFactory(Protocol):
    def __call__(self, client: httpx.AsyncClient, config: dict[str, object]) -> DownloadSourcePort:
        ...

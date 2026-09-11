from typing import Protocol

from app.domain.models import TrackQuery, TrackRef


class SearchPort(Protocol):
    async def search(self, query: TrackQuery) -> list[TrackRef]: ...

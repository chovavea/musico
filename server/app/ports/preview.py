from typing import Protocol

from app.domain.models import PreviewInfo, TrackRef


class PreviewPort(Protocol):
    async def preview(self, track: TrackRef) -> PreviewInfo: ...

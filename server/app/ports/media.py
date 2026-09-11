from typing import Protocol

from app.domain.models import MediaRef, TrackRef


class MediaPort(Protocol):
    async def resolve_media(self, track: TrackRef) -> MediaRef | None:
        ...

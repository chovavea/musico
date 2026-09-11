from __future__ import annotations

import httpx

from app.domain.models import PreviewInfo, TrackRef


def official_outer_url(song_id: str) -> str:
    return f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"


class NeteasePreview:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def preview(self, track: TrackRef) -> PreviewInfo:
        _ = self._client
        return PreviewInfo(preview_url=official_outer_url(track.external_id), quality="low")


def create_preview(client: httpx.AsyncClient) -> NeteasePreview:
    return NeteasePreview(client)

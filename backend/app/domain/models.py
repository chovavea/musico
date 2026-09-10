from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class BoardSpec(BaseModel):
    id: str
    platform: str
    name: str
    type: str
    interval_sec: int
    enabled: bool = True
    overview_slot: Literal["left", "right"] | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class RawRankItem(BaseModel):
    rank: int
    external_id: str
    title: str
    artist: str
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    version: str | None = None
    cover_url: str | None = None
    official_url: str | None = None
    raw_score: float | None = None
    preview_url: str | None = None
    preview_quality: Literal["low", "medium"] | None = None
    preview_expire_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class PreviewInfo(BaseModel):
    preview_url: str | None
    quality: Literal["low", "medium"] | None = None
    expire_at: datetime | None = None


class TrackRef(BaseModel):
    platform: str
    external_id: str
    title: str
    artist: str
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    version: str | None = None


class TrackQuery(BaseModel):
    """Free-text lookup used to borrow a preview from another platform."""

    title: str
    artist: str = ""
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    limit: int = 5


class MediaRef(BaseModel):
    url: str | None = None


class AudioQuality(BaseModel):
    format: str
    sample_rate_hz: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    dsd_rate: str | None = None

    def sort_key(self) -> tuple[int, int, int, int, int]:
        format_rank = {
            "dsf": 4,
            "dff": 4,
            "dsd": 4,
            "wav": 3,
            "flac": 3,
            "alac": 3,
            "aiff": 3,
        }.get(self.format.lower().lstrip("."), 0)
        return (
            format_rank,
            int(self.sample_rate_hz or 0),
            int(self.bit_depth or 0),
            int(self.channels or 0),
            1 if self.dsd_rate else 0,
        )

    def matches_requested(self, requested: AudioQuality) -> bool:
        if self.format.lower().lstrip(".") != requested.format.lower().lstrip("."):
            return False
        for field_name in ("sample_rate_hz", "bit_depth", "channels", "dsd_rate"):
            expected = getattr(requested, field_name)
            if expected is not None and getattr(self, field_name) != expected:
                return False
        return True

    def may_match_requested(self, requested: AudioQuality) -> bool:
        """Allow source metadata to omit dimensions verified after download."""
        if self.format.lower().lstrip(".") != requested.format.lower().lstrip("."):
            return False
        for field_name in ("sample_rate_hz", "bit_depth", "channels", "dsd_rate"):
            actual = getattr(self, field_name)
            expected = getattr(requested, field_name)
            if actual is not None and expected is not None and actual != expected:
                return False
        return True


class DownloadCandidate(BaseModel):
    source_id: str
    source_track_id: str
    title: str
    artist: str
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    version: str | None = None
    quality: AudioQuality
    source_page_url: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)


class DownloadResponse(BaseModel):
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    total_bytes: int | None = None
    content_type: str | None = None

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


class MediaRef(BaseModel):
    url: str | None = None

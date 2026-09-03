from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class PlatformRow(Base):
    __tablename__ = "platform"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))


class BoardRow(Base):
    __tablename__ = "board"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform_id: Mapped[str] = mapped_column(ForeignKey("platform.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PlatformSongRow(Base):
    __tablename__ = "platform_song"
    __table_args__ = (UniqueConstraint("platform_id", "external_id", name="uq_platform_song_ext"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    platform_id: Mapped[str] = mapped_column(ForeignKey("platform.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    artist: Mapped[str] = mapped_column(String(512), nullable=False)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    official_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class RankSnapshotRow(Base):
    __tablename__ = "rank_snapshot"
    __table_args__ = (Index("ix_rank_snapshot_board_fetched", "board_id", "fetched_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    board_id: Mapped[str] = mapped_column(ForeignKey("board.id"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RankEntryRow(Base):
    __tablename__ = "rank_entry"
    __table_args__ = (
        Index("ix_rank_entry_snapshot_rank", "snapshot_id", "rank"),
        Index("ix_rank_entry_song_snapshot", "platform_song_id", "snapshot_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("rank_snapshot.id"), nullable=False)
    platform_song_id: Mapped[str] = mapped_column(ForeignKey("platform_song.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_score: Mapped[float] = mapped_column(Float, nullable=False)
    previous_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_quality: Mapped[str | None] = mapped_column(String(16), nullable=True)
    preview_expire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BoardLatestRow(Base):
    __tablename__ = "board_latest"

    board_id: Mapped[str] = mapped_column(ForeignKey("board.id"), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("rank_snapshot.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderHealthRow(Base):
    __tablename__ = "provider_health"

    board_id: Mapped[str] = mapped_column(ForeignKey("board.id"), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CatalogChartOrderRow(Base):
    __tablename__ = "catalog_chart_order"

    platform_id: Mapped[str] = mapped_column(ForeignKey("platform.id"), primary_key=True)
    chart_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

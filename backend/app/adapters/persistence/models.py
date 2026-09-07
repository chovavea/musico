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
    JSON,
    BigInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LibraryBase(DeclarativeBase):
    pass


LIBRARY_SCHEMA = "musico_library"


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


class LibraryTrackRow(LibraryBase):
    __tablename__ = "library_track"
    __table_args__ = (
        Index("ix_library_track_identity", "normalized_title", "normalized_artist"),
        {"schema": LIBRARY_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    artist: Mapped[str] = mapped_column(String(512), nullable=False)
    album: Mapped[str | None] = mapped_column(String(512), nullable=True)
    normalized_title: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_artist: Mapped[str] = mapped_column(String(512), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    isrc: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class LibrarySourceRefRow(LibraryBase):
    __tablename__ = "library_source_ref"
    __table_args__ = (
        UniqueConstraint("source_id", "source_track_id", name="uq_library_source_track"),
        Index("ix_library_source_ref_track", "library_track_id"),
        {"schema": LIBRARY_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    library_track_id: Mapped[str] = mapped_column(
        ForeignKey(f"{LIBRARY_SCHEMA}.library_track.id"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_track_id: Mapped[str] = mapped_column(String(512), nullable=False)
    source_page_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class LibraryAssetRow(LibraryBase):
    __tablename__ = "library_asset"
    __table_args__ = (
        UniqueConstraint("library_track_id", "format", "sample_rate_hz", "bit_depth", name="uq_library_asset_quality"),
        Index("ix_library_asset_track_status", "library_track_id", "status"),
        {"schema": LIBRARY_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    library_track_id: Mapped[str] = mapped_column(
        ForeignKey(f"{LIBRARY_SCHEMA}.library_track.id"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    sample_rate_hz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bit_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dsd_rate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DownloadTaskRow(LibraryBase):
    __tablename__ = "download_task"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_download_task_idempotency"),
        Index("ix_download_task_claim", "status", "next_retry_at", "heartbeat_at"),
        {"schema": LIBRARY_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    library_track_id: Mapped[str] = mapped_column(
        ForeignKey(f"{LIBRARY_SCHEMA}.library_track.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="resolving")
    requested_quality: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    selected_quality: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    selected_source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    selected_source_track_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_snapshot: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    bytes_done: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bytes_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DownloadAttemptRow(LibraryBase):
    __tablename__ = "download_attempt"
    __table_args__ = ({"schema": LIBRARY_SCHEMA},)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(
        ForeignKey(f"{LIBRARY_SCHEMA}.download_task.id"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

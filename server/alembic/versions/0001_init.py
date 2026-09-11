"""init schema

Revision ID: 0001_init
Revises:
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_init"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
    )
    op.create_table(
        "board",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("platform_id", sa.String(64), sa.ForeignKey("platform.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "platform_song",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("platform_id", sa.String(64), sa.ForeignKey("platform.id"), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("artist", sa.String(512), nullable=False),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("official_url", sa.Text(), nullable=True),
        sa.UniqueConstraint("platform_id", "external_id", name="uq_platform_song_ext"),
    )
    op.create_table(
        "rank_snapshot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("board_id", sa.String(64), sa.ForeignKey("board.id"), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rank_snapshot_board_fetched", "rank_snapshot", ["board_id", "fetched_at"])
    op.create_table(
        "rank_entry",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("rank_snapshot.id"), nullable=False),
        sa.Column(
            "platform_song_id", sa.String(36), sa.ForeignKey("platform_song.id"), nullable=False
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("raw_score", sa.Float(), nullable=True),
        sa.Column("normalized_score", sa.Float(), nullable=False),
        sa.Column("previous_rank", sa.Integer(), nullable=True),
        sa.Column("preview_url", sa.Text(), nullable=True),
        sa.Column("preview_quality", sa.String(16), nullable=True),
        sa.Column("preview_expire_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rank_entry_snapshot_rank", "rank_entry", ["snapshot_id", "rank"])
    op.create_index("ix_rank_entry_song_snapshot", "rank_entry", ["platform_song_id", "snapshot_id"])
    op.create_table(
        "board_latest",
        sa.Column("board_id", sa.String(64), sa.ForeignKey("board.id"), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("rank_snapshot.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "provider_health",
        sa.Column("board_id", sa.String(64), sa.ForeignKey("board.id"), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_item_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("provider_health")
    op.drop_table("board_latest")
    op.drop_index("ix_rank_entry_song_snapshot", table_name="rank_entry")
    op.drop_index("ix_rank_entry_snapshot_rank", table_name="rank_entry")
    op.drop_table("rank_entry")
    op.drop_index("ix_rank_snapshot_board_fetched", table_name="rank_snapshot")
    op.drop_table("rank_snapshot")
    op.drop_table("platform_song")
    op.drop_table("board")
    op.drop_table("platform")

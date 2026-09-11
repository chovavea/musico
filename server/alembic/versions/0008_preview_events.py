"""record which platform served a listening stream

Revision ID: 0008_preview_events
Revises: 0007_library_asset_quality
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_preview_events"
down_revision: str | Sequence[str] | None = "0007_library_asset_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "musico_library"


def upgrade() -> None:
    op.add_column("platform_song", sa.Column("duration_ms", sa.Integer()))
    op.create_table(
        "preview_event",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("track_key", sa.String(64), nullable=False),
        sa.Column("origin_platform", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("artist", sa.String(512), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("source_platform", sa.String(64)),
        sa.Column("source_external_id", sa.String(128)),
        sa.Column("match_score", sa.Float()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(128)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_preview_event_track_created",
        "preview_event",
        ["track_key", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_preview_event_pair_created",
        "preview_event",
        ["origin_platform", "source_platform", "created_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "preview_source_stat",
        sa.Column("origin_platform", sa.String(64), primary_key=True),
        sa.Column("target_platform", sa.String(64), primary_key=True),
        sa.Column("success", sa.Integer(), nullable=False),
        sa.Column("failure", sa.Integer(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("avg_latency_ms", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("preview_source_stat", schema=SCHEMA)
    op.drop_index("ix_preview_event_pair_created", "preview_event", schema=SCHEMA)
    op.drop_index("ix_preview_event_track_created", "preview_event", schema=SCHEMA)
    op.drop_table("preview_event", schema=SCHEMA)
    op.drop_column("platform_song", "duration_ms")

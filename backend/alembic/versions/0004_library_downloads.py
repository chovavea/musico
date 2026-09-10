"""library and download queue

Revision ID: 0004_library_downloads
Revises: 0003_catalog_chart_order
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_library_downloads"
down_revision: str | Sequence[str] | None = "0003_catalog_chart_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "musico_library"


def upgrade() -> None:
    op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    op.create_table(
        "library_track",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("artist", sa.String(512), nullable=False),
        sa.Column("album", sa.String(512)),
        sa.Column("normalized_title", sa.String(512), nullable=False),
        sa.Column("normalized_artist", sa.String(512), nullable=False),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("isrc", sa.String(64)),
        sa.Column("version", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_library_track_identity",
        "library_track",
        ["normalized_title", "normalized_artist"],
        schema=SCHEMA,
    )
    op.create_table(
        "library_source_ref",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "library_track_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.library_track.id"),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("source_track_id", sa.String(512), nullable=False),
        sa.Column("source_page_url", sa.Text()),
        sa.UniqueConstraint("source_id", "source_track_id", name="uq_library_source_track"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_library_source_ref_track", "library_source_ref", ["library_track_id"], schema=SCHEMA
    )
    op.create_table(
        "library_asset",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "library_track_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.library_track.id"),
            nullable=False,
        ),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("sample_rate_hz", sa.Integer()),
        sa.Column("bit_depth", sa.Integer()),
        sa.Column("channels", sa.Integer()),
        sa.Column("dsd_rate", sa.String(32)),
        sa.Column("relative_path", sa.String(1024), nullable=False, unique=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False, server_default="ready"),
        sa.Column("downloaded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "library_track_id",
            "format",
            "sample_rate_hz",
            "bit_depth",
            name="uq_library_asset_quality",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_library_asset_track_status",
        "library_asset",
        ["library_track_id", "status"],
        schema=SCHEMA,
    )
    op.create_table(
        "download_task",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(512), nullable=False),
        sa.Column(
            "library_track_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.library_track.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="resolving"),
        sa.Column("requested_quality", sa.JSON()),
        sa.Column("selected_quality", sa.JSON()),
        sa.Column("selected_source_id", sa.String(128)),
        sa.Column("selected_source_track_id", sa.String(512)),
        sa.Column("source_page_url", sa.Text()),
        sa.Column("candidate_snapshot", sa.JSON()),
        sa.Column("bytes_done", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("bytes_total", sa.BigInteger()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("idempotency_key", name="uq_download_task_idempotency"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_download_task_claim",
        "download_task",
        ["status", "next_retry_at", "heartbeat_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "download_attempt",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.download_task.id"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("download_attempt", schema=SCHEMA)
    op.drop_index("ix_download_task_claim", table_name="download_task", schema=SCHEMA)
    op.drop_table("download_task", schema=SCHEMA)
    op.drop_index("ix_library_asset_track_status", table_name="library_asset", schema=SCHEMA)
    op.drop_table("library_asset", schema=SCHEMA)
    op.drop_index("ix_library_source_ref_track", table_name="library_source_ref", schema=SCHEMA)
    op.drop_table("library_source_ref", schema=SCHEMA)
    op.drop_index("ix_library_track_identity", table_name="library_track", schema=SCHEMA)
    op.drop_table("library_track", schema=SCHEMA)
    op.execute(sa.text(f"DROP SCHEMA IF EXISTS {SCHEMA}"))

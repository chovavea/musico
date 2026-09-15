"""record link-out fallback attempts for failed downloads

Revision ID: 0009_fallback_events
Revises: 0008_preview_events
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_fallback_events"
down_revision: str | Sequence[str] | None = "0008_preview_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "musico_library"


def upgrade() -> None:
    op.create_table(
        "fallback_event",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36)),
        sa.Column("track_id", sa.String(36)),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("artist", sa.String(512), nullable=False),
        sa.Column("source_id", sa.String(64)),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("share_url", sa.Text()),
        sa.Column("page_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_fallback_event_created",
        "fallback_event",
        ["created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_fallback_event_outcome_created",
        "fallback_event",
        ["outcome", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_fallback_event_outcome_created", "fallback_event", schema=SCHEMA)
    op.drop_index("ix_fallback_event_created", "fallback_event", schema=SCHEMA)
    op.drop_table("fallback_event", schema=SCHEMA)

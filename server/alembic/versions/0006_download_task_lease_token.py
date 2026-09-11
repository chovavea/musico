"""add download task lease ownership

Revision ID: 0006_download_task_lease_token
Revises: 0005_library_track_identity_key
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006_download_task_lease_token"
down_revision: str | Sequence[str] | None = "0005_library_track_identity_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "musico_library"


def upgrade() -> None:
    op.add_column(
        "download_task",
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("download_task", "lease_token", schema=SCHEMA)

"""catalog chart order

Revision ID: 0003_catalog_chart_order
Revises: 0002_board_sort_order
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_catalog_chart_order"
down_revision: str | Sequence[str] | None = "0002_board_sort_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_chart_order",
        sa.Column("platform_id", sa.String(64), sa.ForeignKey("platform.id"), primary_key=True),
        sa.Column("chart_key", sa.String(128), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("catalog_chart_order")

"""include channel layout and DSD rate in asset uniqueness

Revision ID: 0007_library_asset_quality
Revises: 0006_download_task_lease_token
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_library_asset_quality"
down_revision: str | Sequence[str] | None = "0006_download_task_lease_token"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "musico_library"


def upgrade() -> None:
    op.drop_constraint(
        "uq_library_asset_quality",
        "library_asset",
        schema=SCHEMA,
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_library_asset_quality",
        "library_asset",
        [
            "library_track_id",
            "format",
            "sample_rate_hz",
            "bit_depth",
            "channels",
            "dsd_rate",
        ],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_library_asset_quality",
        "library_asset",
        schema=SCHEMA,
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_library_asset_quality",
        "library_asset",
        ["library_track_id", "format", "sample_rate_hz", "bit_depth"],
        schema=SCHEMA,
    )

"""make library track identity insert-safe

Revision ID: 0005_library_track_identity_key
Revises: 0004_library_downloads
Create Date: 2026-09-08
"""

import re
import unicodedata
from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from alembic import op

revision: str = "0005_library_track_identity_key"
down_revision: str | Sequence[str] | None = "0004_library_downloads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "musico_library"


def _merge_duplicate_track(connection: sa.Connection, duplicate_id: str, canonical_id: str) -> None:
    connection.execute(
        sa.text(
            f"""
            DELETE FROM {SCHEMA}.library_asset AS duplicate
            USING {SCHEMA}.library_asset AS canonical
            WHERE duplicate.library_track_id = :duplicate_id
              AND canonical.library_track_id = :canonical_id
              AND (
                (
                    duplicate.format = canonical.format
                    AND duplicate.sample_rate_hz IS NOT DISTINCT FROM canonical.sample_rate_hz
                    AND duplicate.bit_depth IS NOT DISTINCT FROM canonical.bit_depth
                )
                OR duplicate.relative_path = canonical.relative_path
              )
            """
        ),
        {"duplicate_id": duplicate_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA}.library_asset
            SET library_track_id = :canonical_id
            WHERE library_track_id = :duplicate_id
            """
        ),
        {"duplicate_id": duplicate_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text(
            f"""
            DELETE FROM {SCHEMA}.library_source_ref AS duplicate
            USING {SCHEMA}.library_source_ref AS canonical
            WHERE duplicate.library_track_id = :duplicate_id
              AND canonical.library_track_id = :canonical_id
              AND duplicate.source_id = canonical.source_id
              AND duplicate.source_track_id = canonical.source_track_id
            """
        ),
        {"duplicate_id": duplicate_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA}.library_source_ref
            SET library_track_id = :canonical_id
            WHERE library_track_id = :duplicate_id
            """
        ),
        {"duplicate_id": duplicate_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA}.download_task
            SET library_track_id = :canonical_id
            WHERE library_track_id = :duplicate_id
            """
        ),
        {"duplicate_id": duplicate_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text(f"DELETE FROM {SCHEMA}.library_track WHERE id = :duplicate_id"),
        {"duplicate_id": duplicate_id},
    )


def upgrade() -> None:
    op.add_column(
        "library_track",
        sa.Column("identity_key", sa.String(length=64), nullable=True),
        schema=SCHEMA,
    )
    connection = op.get_bind()
    rows = (
        connection.execute(
            sa.text(
                f"""
            SELECT id, title, artist, duration_ms, isrc
            FROM {SCHEMA}.library_track
            """
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        connection.execute(
            sa.text(
                f"UPDATE {SCHEMA}.library_track SET identity_key = :identity_key WHERE id = :id"
            ),
            {
                "id": row["id"],
                "identity_key": _track_identity_key(
                    isrc=row["isrc"],
                    title=row["title"],
                    artist=row["artist"],
                    duration_ms=row["duration_ms"],
                ),
            },
        )
    duplicate_rows = (
        connection.execute(
            sa.text(
                f"""
            SELECT id, identity_key
            FROM {SCHEMA}.library_track
            ORDER BY identity_key, created_at, id
            """
            )
        )
        .mappings()
        .all()
    )
    canonical_by_key: dict[str, str] = {}
    for row in duplicate_rows:
        canonical_id = canonical_by_key.setdefault(row["identity_key"], row["id"])
        if row["id"] != canonical_id:
            _merge_duplicate_track(connection, row["id"], canonical_id)

    op.alter_column(
        "library_track",
        "identity_key",
        existing_type=sa.String(length=64),
        nullable=False,
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_library_track_identity_key",
        "library_track",
        ["identity_key"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_library_track_identity_key",
        "library_track",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_column("library_track", "identity_key", schema=SCHEMA)


# Frozen copies of app.domain.matching helpers so this migration never depends
# on application code that may change later.
def _normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = re.sub(r"\([^)]*?(?:live|remix|instrumental|伴奏|现场)[^)]*\)", "", text)
    text = re.sub(r"\[[^]]*?(?:live|remix|instrumental|伴奏|现场)[^]]*\]", "", text)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)


def _artist_key(value: str | None) -> str:
    artists = re.split(r"\s*(?:/|,|&|和|、|feat\.?|ft\.?)\s*", value or "", flags=re.I)
    return _normalize_text(artists[0] if artists else value)


def _track_identity_key(
    *, isrc: str | None, title: str | None, artist: str | None, duration_ms: int | None
) -> str:
    identity = "|".join(
        (
            isrc.casefold() if isrc else "",
            _normalize_text(title),
            _artist_key(artist),
            str(duration_ms or ""),
        )
    )
    return sha256(identity.encode("utf-8")).hexdigest()

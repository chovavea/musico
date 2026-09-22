"""separate recording versions in library and download identities

Revision ID: 0010_recording_version_identity
Revises: 0009_fallback_events
Create Date: 2026-09-22
"""

import re
import unicodedata
from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from alembic import op

revision: str = "0010_recording_version_identity"
down_revision: str | Sequence[str] | None = "0009_fallback_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "musico_library"

# Frozen version of the identity discriminator, independent of future matching
# changes. Only these traditional characters occur in the recognized markers.
_TRADITIONAL = str.maketrans("現場電純樂鈴聲", "现场电纯乐铃声")
_ASCII = ("live", "remix", "instrumental", "acoustic", "unplugged")
_CJK = ("伴奏", "现场", "翻唱", "不插电", "片段", "铃声", "纯音乐", "加速版", "慢速版")
_VERSION_BRACKET_RE = re.compile(
    r"\([^)]*?(?:live|remix|instrumental|伴奏|现场)[^)]*\)"
    r"|\[[^]]*?(?:live|remix|instrumental|伴奏|现场)[^]]*\]"
)


def _strip_version_brackets(text: str) -> str:
    folded = text.translate(_TRADITIONAL)
    spans = [match.span() for match in _VERSION_BRACKET_RE.finditer(folded)]
    if not spans or len(folded) != len(text):
        return text
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = _strip_version_brackets(text)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)


def _artist_key(value: str | None) -> str:
    artists = re.split(r"\s*(?:/|,|&|和|、|feat\.?|ft\.?)\s*", value or "", flags=re.I)
    return _normalize(artists[0] if artists else value)


def _folded(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold().translate(_TRADITIONAL)


def _edition_beyond_markers(version: str | None) -> str:
    """Mirror ``matching._edition_beyond_markers`` for this frozen discriminator."""
    stripped = _folded(version)
    for marker in sorted(_CJK, key=len, reverse=True):
        stripped = stripped.replace(marker, " ")
    for marker in _ASCII:
        stripped = re.sub(rf"(?<![a-z]){marker}(?![a-z])", " ", stripped)
    for filler in ("edition", "version"):
        stripped = re.sub(rf"(?<![a-z]){filler}(?![a-z])", " ", stripped)
    return _normalize(stripped.replace("版", " "))


def _version_key(title: str, version: str | None) -> str:
    text = _folded(f"{title} {version or ''}")
    markers = {marker for marker in _CJK if marker in text}
    markers.update(
        marker for marker in _ASCII if re.search(rf"(?<![a-z]){marker}(?![a-z])", text)
    )
    parts = sorted(markers)
    if _edition_beyond_markers(version):
        parts.append(f"version:{_normalize(_folded(version))}")
    return "|".join(parts)


def _rekey(key: str, version: str) -> str:
    return sha256(f"{key}|recording:{version}".encode()).hexdigest()


def _legacy_identity(
    *, isrc: str | None, title: str | None, artist: str | None, duration_ms: int | None
) -> str:
    identity = "|".join(
        (
            isrc.casefold() if isrc else "",
            _normalize(title),
            _artist_key(artist),
            str(duration_ms or ""),
        )
    )
    return sha256(identity.encode()).hexdigest()


def _identity_key(
    *,
    isrc: str | None,
    title: str | None,
    artist: str | None,
    duration_ms: int | None,
    version: str | None,
) -> str:
    legacy = _legacy_identity(isrc=isrc, title=title, artist=artist, duration_ms=duration_ms)
    marker = _version_key(title or "", version)
    if not marker:
        return legacy
    return _rekey(legacy, marker)


def _merge_track(connection: sa.Connection, duplicate_id: str, canonical_id: str) -> None:
    """Keep one row when traditional and simplified version titles collide."""
    canonical_assets = connection.execute(
        sa.text(
            f"SELECT format, sample_rate_hz, bit_depth, channels, dsd_rate, relative_path "
            f"FROM {SCHEMA}.library_asset WHERE library_track_id = :track_id"
        ),
        {"track_id": canonical_id},
    ).mappings().all()
    occupied = {
        (
            row["format"],
            row["sample_rate_hz"],
            row["bit_depth"],
            row["channels"],
            row["dsd_rate"],
        )
        for row in canonical_assets
    }
    paths = {row["relative_path"] for row in canonical_assets}
    duplicates = connection.execute(
        sa.text(
            f"SELECT id, format, sample_rate_hz, bit_depth, channels, dsd_rate, relative_path "
            f"FROM {SCHEMA}.library_asset WHERE library_track_id = :track_id"
        ),
        {"track_id": duplicate_id},
    ).mappings().all()
    for asset in duplicates:
        quality = (
            asset["format"],
            asset["sample_rate_hz"],
            asset["bit_depth"],
            asset["channels"],
            asset["dsd_rate"],
        )
        if quality in occupied or asset["relative_path"] in paths:
            connection.execute(
                sa.text(f"DELETE FROM {SCHEMA}.library_asset WHERE id = :id"),
                {"id": asset["id"]},
            )
            continue
        connection.execute(
            sa.text(
                f"UPDATE {SCHEMA}.library_asset SET library_track_id = :canonical "
                "WHERE id = :id"
            ),
            {"canonical": canonical_id, "id": asset["id"]},
        )
    connection.execute(
        sa.text(
            f"UPDATE {SCHEMA}.library_source_ref SET library_track_id = :canonical "
            "WHERE library_track_id = :duplicate"
        ),
        {"canonical": canonical_id, "duplicate": duplicate_id},
    )
    connection.execute(
        sa.text(
            f"UPDATE {SCHEMA}.download_task SET library_track_id = :canonical "
            "WHERE library_track_id = :duplicate"
        ),
        {"canonical": canonical_id, "duplicate": duplicate_id},
    )
    connection.execute(
        sa.text(
            f"UPDATE {SCHEMA}.fallback_event SET track_id = :canonical WHERE track_id = :duplicate"
        ),
        {"canonical": canonical_id, "duplicate": duplicate_id},
    )
    connection.execute(
        sa.text(f"DELETE FROM {SCHEMA}.library_track WHERE id = :id"),
        {"id": duplicate_id},
    )


def upgrade() -> None:
    connection = op.get_bind()
    tracks = connection.execute(
        sa.text(
            f"SELECT id, title, artist, duration_ms, isrc, version, identity_key, "
            f"normalized_title, normalized_artist FROM {SCHEMA}.library_track"
        )
    ).mappings().all()
    planned: list[dict[str, object]] = []
    for track in tracks:
        version = _version_key(track["title"], track["version"])
        planned.append(
            {
                "id": track["id"],
                "identity": _identity_key(
                    isrc=track["isrc"],
                    title=track["title"],
                    artist=track["artist"],
                    duration_ms=track["duration_ms"],
                    version=track["version"],
                ),
                "title_norm": _normalize(track["title"]),
                "artist_norm": _artist_key(track["artist"]),
                "version": version,
                "old_identity": track["identity_key"],
                "old_title": track["normalized_title"],
                "old_artist": track["normalized_artist"],
            }
        )
    groups: dict[str, list[dict[str, object]]] = {}
    for item in planned:
        groups.setdefault(str(item["identity"]), []).append(item)
    for group in groups.values():
        group.sort(key=lambda item: str(item["id"]))
        canonical = group[0]
        for duplicate in group[1:]:
            _merge_track(connection, str(duplicate["id"]), str(canonical["id"]))
        if (
            canonical["identity"] != canonical["old_identity"]
            or canonical["title_norm"] != canonical["old_title"]
            or canonical["artist_norm"] != canonical["old_artist"]
        ):
            connection.execute(
                sa.text(
                    f"UPDATE {SCHEMA}.library_track SET identity_key = :key, "
                    "normalized_title = :title, normalized_artist = :artist WHERE id = :id"
                ),
                {
                    "id": canonical["id"],
                    "key": canonical["identity"],
                    "title": canonical["title_norm"],
                    "artist": canonical["artist_norm"],
                },
            )
        version = str(canonical["version"])
        if not version:
            continue
        # Preserve each task's original request/quality hash, not the library
        # row's potentially enriched metadata. Active tasks retain their ids,
        # leases, candidate snapshots and partial files.
        tasks = connection.execute(
            sa.text(
                f"SELECT id, idempotency_key FROM {SCHEMA}.download_task "
                "WHERE library_track_id = :track_id"
            ),
            {"track_id": canonical["id"]},
        ).mappings().all()
        for task in tasks:
            connection.execute(
                sa.text(
                    f"UPDATE {SCHEMA}.download_task SET idempotency_key = :key WHERE id = :id"
                ),
                {"id": task["id"], "key": _rekey(task["idempotency_key"], version)},
            )


def downgrade() -> None:
    # Old identities cannot represent studio and live rows simultaneously.
    # Refuse rather than merge records, delete assets or silently change tasks.
    raise RuntimeError("Recording-version identities require a backup to downgrade safely")

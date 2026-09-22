from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from app.adapters.persistence.library_repository import LibraryRepository, task_idempotency_key
from app.adapters.persistence.models import (
    DownloadTaskRow,
    LibraryAssetRow,
    LibraryBase,
    LibraryTrackRow,
)
from app.domain.matching import (
    artist_key,
    is_auto_match,
    is_same_recording,
    legacy_track_key,
    normalize_text,
    recording_version_key,
    track_key,
)
from app.domain.models import AudioQuality, TrackRef
from app.services.downloads import DownloadService
from app.settings import Settings
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

STUDIO = TrackRef(platform="test", external_id="studio", title="Song", artist="Artist")


@pytest.mark.parametrize(
    "title,version",
    [
        ("Song (Live)", None),
        ("Song (Remix)", None),
        ("Song", "Live"),
        ("Song", "2020 edition"),
        ("Song", "现场版"),
        ("Song", "現場"),
    ],
)
async def test_downloading_another_version_never_reuses_or_renames_studio(
    tmp_path: Path, title: str, version: str | None
) -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={"schema_translate_map": {"musico_library": None}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(LibraryBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        settings = Settings(
            _env_file=None,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            MUSIC_LIBRARY_DIR=tmp_path,
        )
        service = DownloadService(factory, settings)
        (tmp_path / "studio.flac").write_bytes(b"fixture audio")
        async with factory() as session:
            row = await LibraryRepository(session).find_or_create_track(STUDIO)
            studio_id = row.id
            session.add(
                LibraryAssetRow(
                    id="studio-asset",
                    library_track_id=studio_id,
                    format="flac",
                    relative_path="studio.flac",
                    status="ready",
                )
            )
            await session.commit()
        other = STUDIO.model_copy(
            update={"external_id": "other", "title": title, "version": version}
        )
        response = await service.request(other)
        assert response["state"] == "queued"
        assert response["task"]["track_id"] != studio_id
        again = await service.request(other)
        assert again["task"]["id"] == response["task"]["id"]
        studio = await service.request(STUDIO)
        assert studio["state"] == "ready"
        assert studio["asset"]["id"] == "studio-asset"
        assert studio["asset"]["title"] == "Song"
        async with factory() as session:
            assert len((await session.scalars(select(LibraryTrackRow))).all()) == 2
    finally:
        await engine.dispose()


async def test_same_isrc_live_request_keeps_the_studio_identity(tmp_path: Path) -> None:
    studio = STUDIO.model_copy(update={"isrc": "USRC12345678", "duration_ms": 200_000})
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={"schema_translate_map": {"musico_library": None}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(LibraryBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        settings = Settings(
            _env_file=None,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            MUSIC_LIBRARY_DIR=tmp_path,
        )
        service = DownloadService(factory, settings)
        (tmp_path / "studio.flac").write_bytes(b"fixture audio")
        async with factory() as session:
            row = await LibraryRepository(session).find_or_create_track(studio)
            studio_id = row.id
            session.add(
                LibraryAssetRow(
                    id="studio-asset",
                    library_track_id=studio_id,
                    format="flac",
                    relative_path="studio.flac",
                    status="ready",
                )
            )
            await session.commit()
        live = studio.model_copy(
            update={"external_id": "live", "title": "Song (Live)", "isrc": "usrc12345678"}
        )
        response = await service.request(live)
        assert response["state"] == "queued"
        assert response["task"]["track_id"] != studio_id
        again = await service.request(studio)
        assert again["state"] == "ready"
        assert again["asset"]["id"] == "studio-asset"
        assert again["asset"]["title"] == "Song"
        async with factory() as session:
            stored = await session.get(LibraryTrackRow, studio_id)
            assert stored is not None
            assert stored.title == "Song"
            assert stored.identity_key == track_key(studio)
    finally:
        await engine.dispose()


def test_version_keys_and_matching_distinguish_live_from_remix() -> None:
    live = STUDIO.model_copy(update={"title": "Song (Live)"})
    remix = STUDIO.model_copy(update={"title": "Song (Remix)"})
    explicit_live = STUDIO.model_copy(update={"version": "Live"})
    assert track_key(STUDIO) == legacy_track_key(STUDIO)
    assert track_key(live) == track_key(explicit_live)
    assert len({track_key(STUDIO), track_key(live), track_key(remix)}) == 3
    assert is_same_recording(live, explicit_live)
    assert not is_same_recording(live, remix)
    assert not is_auto_match(STUDIO, live)
    assert not is_auto_match(live, remix)
    in_title = [
        STUDIO.model_copy(update={"title": "Song (现场版)"}),
        STUDIO.model_copy(update={"title": "Song (現場)"}),
        STUDIO.model_copy(update={"title": "Song (Live Version)"}),
    ]
    in_field = [
        STUDIO.model_copy(update={"version": "现场版"}),
        STUDIO.model_copy(update={"version": "現場"}),
        STUDIO.model_copy(update={"version": "Live Version"}),
    ]
    assert track_key(in_title[0]) == track_key(in_title[1]) == track_key(in_field[0])
    assert track_key(in_field[0]) == track_key(in_field[1])
    assert track_key(in_title[2]) == track_key(in_field[2])
    assert track_key(in_title[0]) != track_key(in_title[2])
    assert all(
        is_same_recording(left, right) for left, right in zip(in_title, in_field, strict=True)
    )
    shared_isrc = STUDIO.model_copy(update={"isrc": "USRC12345678", "duration_ms": 200_000})
    live_isrc = shared_isrc.model_copy(
        update={"external_id": "live", "title": "Song (Live)", "isrc": "usrc12345678"}
    )
    assert not is_same_recording(shared_isrc, live_isrc)
    assert not is_auto_match(shared_isrc, live_isrc)
    assert track_key(shared_isrc) != track_key(live_isrc)


def _migration():
    path = (
        Path(__file__).resolve().parents[2] / "alembic/versions/0010_recording_version_identity.py"
    )
    spec = importlib.util.spec_from_file_location("recording_identity_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_identity_matches_runtime_for_version_spellings() -> None:
    migration = _migration()
    samples = [
        STUDIO.model_copy(update={"title": "Song (現場)"}),
        STUDIO.model_copy(update={"version": "現場"}),
        STUDIO.model_copy(update={"title": "Song (现场版)"}),
        STUDIO.model_copy(update={"version": "现场版"}),
        STUDIO.model_copy(update={"title": "Song (Live Version)"}),
        STUDIO.model_copy(update={"isrc": "USRC12345678", "title": "Song (Live)"}),
    ]
    for track in samples:
        assert migration._identity_key(
            isrc=track.isrc,
            title=track.title,
            artist=track.artist,
            duration_ms=track.duration_ms,
            version=track.version,
        ) == track_key(track)


@pytest.mark.parametrize(
    "title,version",
    [
        ("Song", None),
        ("Song (LIVE)", None),
        ("Song (Remix)", None),
        ("Song (現場)", None),
        ("Song (純音樂)", None),
        ("Song (不插電)", None),
        ("Song", "Live"),
        ("Song", "Live Version"),
        ("Song", "2020 edition"),
        ("Song (现场版)", None),
        ("Song", "现场版"),
        ("Song", "現場"),
        ("Song", "純音樂"),
    ],
)
def test_frozen_migration_discriminator_matches_runtime(
    title: str, version: str | None
) -> None:
    track = STUDIO.model_copy(update={"title": title, "version": version})
    assert _migration()._version_key(title, version) == recording_version_key(track)


def test_migration_preserves_active_task_identity_and_quality(monkeypatch) -> None:
    migration = _migration()
    live = STUDIO.model_copy(update={"title": "Song (Live)", "duration_ms": 240_000})
    quality = AudioQuality(format="flac", bit_depth=24)
    quality_payload = json.dumps(
        quality.model_dump(mode="json", exclude_none=True), sort_keys=True, separators=(",", ":")
    )
    legacy_quality_key = hashlib.sha256(
        f"{legacy_track_key(live)}|quality:{quality_payload}".encode()
    ).hexdigest()
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS musico_library")
            LibraryBase.metadata.create_all(connection)
            # The library metadata may have been enriched after the task was
            # created; its original quality-specific key must still be retained.
            enriched_live = live.model_copy(update={"duration_ms": 241_000})
            for name, track in [("studio", STUDIO), ("live", enriched_live)]:
                connection.execute(
                    LibraryTrackRow.__table__.insert().values(
                        id=name,
                        identity_key=legacy_track_key(track),
                        title=track.title,
                        artist=track.artist,
                        duration_ms=track.duration_ms,
                        normalized_title=normalize_text(track.title),
                        normalized_artist=artist_key(track.artist),
                    )
                )
            for name, key in [
                ("default", legacy_track_key(live)),
                ("quality", legacy_quality_key),
            ]:
                connection.execute(
                    DownloadTaskRow.__table__.insert().values(
                        id=name, library_track_id="live", idempotency_key=key,
                        status="downloading", bytes_done=123, attempt_count=1,
                    )
                )
            monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
            migration.upgrade()
            tracks = dict(connection.execute(
                select(LibraryTrackRow.id, LibraryTrackRow.identity_key)
            ).all())
            assert tracks == {
                "studio": track_key(STUDIO),
                "live": track_key(enriched_live),
            }
            tasks = connection.execute(
                select(DownloadTaskRow.__table__).order_by(DownloadTaskRow.id)
            ).mappings().all()
            assert tasks[0]["idempotency_key"] == task_idempotency_key(live)
            assert tasks[1]["idempotency_key"] == task_idempotency_key(live, quality)
            assert all(
                task["status"] == "downloading" and task["bytes_done"] == 123 for task in tasks
            )
    finally:
        engine.dispose()

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from app.settings import Settings, _ensure_local_database_url, apply_file_env, get_settings

_MANAGED_KEYS = (
    "DATABASE_URL",
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_USER",
    "DATABASE_NAME",
    "DATABASE_PASSWORD",
    "DATABASE_PASSWORD_FILE",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
)


@pytest.fixture(autouse=True)
def _clean_database_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the developer's own shell out of these assertions."""
    for key in _MANAGED_KEYS:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    for key in _MANAGED_KEYS:
        os.environ.pop(key, None)
    get_settings.cache_clear()


def test_database_url_is_assembled_from_parts() -> None:
    settings = Settings(DATABASE_HOST="db.internal", DATABASE_NAME="library")

    assert settings.database_url == "postgresql+psycopg://musico@db.internal:5432/library"


def test_password_and_port_are_honoured() -> None:
    settings = Settings(DATABASE_PORT=5433, DATABASE_USER="listener", DATABASE_PASSWORD="p@ss/word")

    assert settings.database_url == "postgresql+psycopg://listener:p%40ss%2Fword@127.0.0.1:5433/musico"


def test_explicit_database_url_wins_over_the_parts() -> None:
    settings = Settings(
        DATABASE_URL="postgresql+psycopg://forced@elsewhere:6000/other",
        DATABASE_HOST="db.internal",
    )

    assert settings.database_url == "postgresql+psycopg://forced@elsewhere:6000/other"


def test_nothing_configured_keeps_the_local_default() -> None:
    assert Settings().database_url == "postgresql+psycopg://musico@127.0.0.1:5432/musico"


def test_file_env_resolves_a_secret_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "db_password"
    secret.write_text("file-value\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_PASSWORD_FILE", str(secret))

    apply_file_env()

    assert os.environ["DATABASE_PASSWORD"] == "file-value"


def test_file_env_keeps_an_explicit_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "db_password"
    secret.write_text("from-file", encoding="utf-8")
    monkeypatch.setenv("DATABASE_PASSWORD_FILE", str(secret))
    monkeypatch.setenv("DATABASE_PASSWORD", "from-env")

    apply_file_env()

    assert os.environ["DATABASE_PASSWORD"] == "from-env"


def test_file_env_refuses_a_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_PASSWORD_FILE", str(tmp_path / "absent"))

    with pytest.raises(RuntimeError, match="not readable"):
        apply_file_env()


def test_file_env_refuses_an_empty_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "db_password"
    empty.write_text("\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_PASSWORD_FILE", str(empty))

    with pytest.raises(RuntimeError, match="is empty"):
        apply_file_env()


def test_get_settings_resolves_the_file_before_building_the_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deployment contract: DATABASE_HOST + DATABASE_PASSWORD_FILE, no DATABASE_URL."""
    secret = tmp_path / "db_password"
    secret.write_text("file-value", encoding="utf-8")
    monkeypatch.setenv("DATABASE_HOST", "musico-postgres")
    monkeypatch.setenv("DATABASE_NAME", "music")
    monkeypatch.setenv("DATABASE_PASSWORD_FILE", str(secret))

    settings = get_settings()

    assert settings.database_url == (
        "postgresql+psycopg://musico:file-value@musico-postgres:5432/music"
    )


def test_postgres_vars_do_not_hijack_an_explicit_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """A container that carries POSTGRES_* must not be redirected to 127.0.0.1."""
    monkeypatch.setenv("DATABASE_HOST", "musico-postgres")
    monkeypatch.setenv("POSTGRES_USER", "musico")
    monkeypatch.setenv("POSTGRES_DB", "musico")
    monkeypatch.setenv("POSTGRES_PASSWORD", "unused-here")

    _ensure_local_database_url()

    assert "DATABASE_URL" not in os.environ
    assert Settings().database_url == "postgresql+psycopg://musico@musico-postgres:5432/musico"


def test_postgres_vars_still_build_the_local_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "musico")
    monkeypatch.setenv("POSTGRES_DB", "musico")
    monkeypatch.setenv("POSTGRES_PASSWORD", "local-dev")

    _ensure_local_database_url()

    assert os.environ["DATABASE_URL"] == "postgresql+psycopg://musico:local-dev@127.0.0.1:5432/musico"

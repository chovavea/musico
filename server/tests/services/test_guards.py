from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.adapters.http.routes import _invalidate_library_cache, _raw_catalog_platforms
from app.main import create_app
from app.services.boards_config import BoardsConfigError, load_raw_boards, parse_board_specs
from app.settings import Settings


def test_duplicate_id_is_fatal(tmp_path: Path) -> None:
    path = tmp_path / "boards.yaml"
    path.write_text(
        """
boards:
  - id: a
    platform: qqmusic
    name: A
    type: hot
    enabled: true
    interval_sec: 10
    extra: {top_id: 26}
  - id: a
    platform: netease
    name: B
    type: hot
    enabled: true
    interval_sec: 10
    extra: {playlist_id: "1"}
""",
        encoding="utf-8",
    )
    with pytest.raises(BoardsConfigError):
        parse_board_specs(load_raw_boards(path))
    settings = Settings(boards_yaml=path, enable_media_resolver=False)
    with pytest.raises(SystemExit):
        create_app(settings, start_scheduler=False, run_migrations=False)


def test_media_resolver_without_impl_exits(tmp_path: Path) -> None:
    src = Path(__file__).resolve().parents[3] / "configs" / "boards.yaml"
    settings = Settings(boards_yaml=src, enable_media_resolver=True)
    with pytest.raises(SystemExit) as exc:
        create_app(settings, start_scheduler=False, run_migrations=False)
    assert exc.value.code == 1


def test_library_cache_invalidation_keeps_catalog_definition_cache() -> None:
    cache = {
        "latest:board": {"data": {}},
        "catalog:qqmusic:hot": {"data": {}},
        "catalog:raw": {"data": {}},
        "unrelated": {"data": {}},
    }

    _invalidate_library_cache(cache)

    assert set(cache) == {"catalog:raw", "unrelated"}


def _fake_request(cache: dict[str, Any]) -> Any:
    """The helper only reads ``app.state.latest_cache`` and the platform registry."""
    state = SimpleNamespace(latest_cache=cache, registry=SimpleNamespace(platform_names=lambda: {}))
    return SimpleNamespace(app=SimpleNamespace(state=state))


@pytest.mark.asyncio
async def test_raw_catalog_platforms_reuses_a_cached_list() -> None:
    cached = [{"id": "qqmusic", "name": "QQ", "groups": []}]
    request = _fake_request({"catalog:raw": {"ts": time.time(), "data": cached}})

    assert await _raw_catalog_platforms(request) == cached


@pytest.mark.asyncio
async def test_raw_catalog_platforms_refetches_a_cache_entry_that_is_not_a_list() -> None:
    cache: dict[str, Any] = {"catalog:raw": {"ts": time.time(), "data": "stale"}}
    request = _fake_request(cache)

    assert await _raw_catalog_platforms(request) == []
    assert cache["catalog:raw"]["data"] == []

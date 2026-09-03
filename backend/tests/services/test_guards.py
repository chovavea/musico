from __future__ import annotations

from pathlib import Path

import pytest

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

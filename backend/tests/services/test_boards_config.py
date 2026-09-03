from __future__ import annotations

from pathlib import Path

import pytest

from app.services.boards_config import (
    BoardsConfigError,
    extra_errors,
    load_raw_boards,
    parse_board_specs,
)


def test_duplicate_board_id(tmp_path: Path) -> None:
    path = tmp_path / "boards.yaml"
    path.write_text(
        """
boards:
  - id: qq_hot
    platform: qqmusic
    name: A
    type: hot
    enabled: true
    interval_sec: 1800
    extra: { top_id: 26 }
  - id: qq_hot
    platform: netease
    name: B
    type: hot
    enabled: true
    interval_sec: 1800
    extra: { playlist_id: "1" }
""",
        encoding="utf-8",
    )
    with pytest.raises(BoardsConfigError, match="duplicate"):
        parse_board_specs(load_raw_boards(path))


def test_invalid_interval(tmp_path: Path) -> None:
    path = tmp_path / "boards.yaml"
    path.write_text(
        """
boards:
  - id: qq_hot
    platform: qqmusic
    name: A
    type: hot
    enabled: true
    interval_sec: 0
    extra: { top_id: 26 }
""",
        encoding="utf-8",
    )
    with pytest.raises(BoardsConfigError, match="interval_sec"):
        parse_board_specs(load_raw_boards(path))


def test_extra_required_missing() -> None:
    errors = extra_errors({}, {"required": ["top_id"], "types": {"top_id": "int"}})
    assert errors == ["missing required extra.top_id"]


def test_duplicate_overview_slot(tmp_path: Path) -> None:
    path = tmp_path / "boards.yaml"
    path.write_text(
        """
boards:
  - id: qq_hot
    platform: qqmusic
    name: A
    type: hot
    enabled: true
    overview_slot: left
    interval_sec: 1800
    extra: { top_id: 26 }
  - id: netease_hot
    platform: netease
    name: B
    type: hot
    enabled: true
    overview_slot: left
    interval_sec: 1800
    extra: { playlist_id: "1" }
""",
        encoding="utf-8",
    )
    with pytest.raises(BoardsConfigError, match="overview_slot"):
        parse_board_specs(load_raw_boards(path))


def test_repo_yaml_slots() -> None:
    src = Path(__file__).resolve().parents[3] / "configs" / "boards.yaml"
    specs = parse_board_specs(load_raw_boards(src))
    by_id = {spec.id: spec for spec in specs}
    assert by_id["qq_hot"].overview_slot == "left"
    assert by_id["netease_hot"].overview_slot == "right"
    assert by_id["qq_douyin"].type == "douyin"
    assert by_id["qq_douyin"].overview_slot is None


def test_extra_type_mismatch() -> None:
    errors = extra_errors({"top_id": "26"}, {"required": ["top_id"], "types": {"top_id": "int"}})
    assert "must be int" in errors[0]

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.domain.models import BoardSpec


class BoardsConfigError(ValueError):
    """Fatal boards.yaml error; process should exit."""


_TYPE_CHECKERS: dict[str, type[object]] = {
    "str": str,
    "int": int,
    "bool": bool,
}


def load_raw_boards(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise BoardsConfigError(f"boards.yaml not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("boards"), list):
        raise BoardsConfigError("boards.yaml must contain a top-level boards list")
    boards = payload["boards"]
    if not boards:
        raise BoardsConfigError("boards.yaml has no boards")
    return [item for item in boards if isinstance(item, dict)]


def parse_board_specs(raw_boards: list[dict[str, Any]]) -> list[BoardSpec]:
    seen: set[str] = set()
    specs: list[BoardSpec] = []
    for item in raw_boards:
        board_id = str(item.get("id", "")).strip()
        if not board_id:
            raise BoardsConfigError("board id is required")
        if board_id in seen:
            raise BoardsConfigError(f"duplicate board id: {board_id}")
        seen.add(board_id)
        interval = item.get("interval_sec")
        if not isinstance(interval, int) or interval <= 0:
            raise BoardsConfigError(f"{board_id}: interval_sec must be a positive integer")
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise BoardsConfigError(f"{board_id}: enabled must be a boolean")
        extra = item.get("extra") or {}
        if extra is None:
            extra = {}
        if not isinstance(extra, dict):
            raise BoardsConfigError(f"{board_id}: extra must be a mapping")
        slot = item.get("overview_slot")
        if slot in ("", None):
            slot = None
        elif slot not in ("left", "right"):
            raise BoardsConfigError(f"{board_id}: overview_slot must be left or right")
        try:
            specs.append(
                BoardSpec(
                    id=board_id,
                    platform=str(item.get("platform", "")).strip(),
                    name=str(item.get("name", board_id)),
                    type=str(item.get("type", "hot")),
                    interval_sec=interval,
                    enabled=enabled,
                    overview_slot=slot,
                    extra=extra,
                )
            )
        except ValidationError as exc:
            raise BoardsConfigError(f"{board_id}: invalid spec: {exc}") from exc
        if not specs[-1].platform:
            raise BoardsConfigError(f"{board_id}: platform is required")
    slots = [spec.overview_slot for spec in specs if spec.overview_slot]
    if len(slots) != len(set(slots)):
        raise BoardsConfigError("overview_slot left/right must be unique")
    return specs


def extra_errors(extra: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = schema.get("required") or []
    if not isinstance(required, list):
        return ["config_schema.required must be a list"]
    types = schema.get("types") or {}
    if types is not None and not isinstance(types, dict):
        return ["config_schema.types must be a mapping"]
    for key in required:
        if key not in extra:
            errors.append(f"missing required extra.{key}")
    if isinstance(types, dict):
        for key, type_name in types.items():
            if key not in extra:
                continue
            expected = _TYPE_CHECKERS.get(str(type_name))
            if expected is None:
                errors.append(f"unsupported type for extra.{key}: {type_name}")
                continue
            if not isinstance(extra[key], expected):
                errors.append(f"extra.{key} must be {type_name}")
    return errors

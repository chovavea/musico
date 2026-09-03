from __future__ import annotations

import importlib
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx
import structlog

from app.domain.models import BoardSpec
from app.ports.chart import ChartPort
from app.ports.media import MediaPort
from app.ports.preview import PreviewPort
from app.services.boards_config import extra_errors

log = structlog.get_logger(__name__)


@dataclass
class PluginRecord:
    plugin_id: str
    name: str
    capabilities: list[str]
    config_schema: dict[str, Any]
    chart: ChartPort | None = None
    preview: PreviewPort | None = None
    media: MediaPort | None = None


@dataclass
class PluginRegistry:
    plugins: dict[str, PluginRecord] = field(default_factory=dict)

    def get(self, platform: str) -> PluginRecord | None:
        return self.plugins.get(platform)

    def has_media_port(self) -> bool:
        return any(record.media is not None for record in self.plugins.values())

    def platform_names(self) -> dict[str, str]:
        return {key: rec.name for key, rec in self.plugins.items()}

    def extra_ok(self, spec: BoardSpec) -> list[str]:
        record = self.plugins.get(spec.platform)
        if record is None:
            return [f"unknown platform: {spec.platform}"]
        return extra_errors(spec.extra, record.config_schema)


def load_registry(client: httpx.AsyncClient) -> PluginRegistry:
    root = Path(__file__).resolve().parent
    registry = PluginRegistry()
    for toml_path in sorted(root.glob("*/plugin.toml")):
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        plugin_id = str(data["id"])
        package = f"app.plugins.{toml_path.parent.name}"
        capabilities = [str(item) for item in data.get("capabilities", [])]
        schema = data.get("config_schema") or {}
        if not isinstance(schema, dict):
            raise ValueError(f"{plugin_id}: config_schema must be a table")
        record = PluginRecord(
            plugin_id=plugin_id,
            name=str(data.get("name", plugin_id)),
            capabilities=capabilities,
            config_schema=schema,
        )
        if "chart" in capabilities:
            module = importlib.import_module(f"{package}.charts")
            factory = getattr(module, "create_chart")
            chart = factory(client)
            record.chart = chart
        if "preview" in capabilities:
            module = importlib.import_module(f"{package}.preview")
            factory = getattr(module, "create_preview")
            record.preview = factory(client)
        if "media" in capabilities:
            module = importlib.import_module(f"{package}.media")
            factory = getattr(module, "create_media")
            record.media = factory(client)
        registry.plugins[plugin_id] = record
        log.info("plugin_loaded", plugin_id=plugin_id, capabilities=capabilities)
    return registry

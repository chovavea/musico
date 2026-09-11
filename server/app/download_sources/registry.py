from __future__ import annotations

import importlib
import importlib.util
import os
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from app.download_sources.protocol import DownloadSourcePort

log = structlog.get_logger(__name__)


@dataclass
class DownloadSourceRecord:
    source_id: str
    name: str
    priority: int
    hosts: tuple[str, ...]
    config_schema: dict[str, Any]
    source: DownloadSourcePort


@dataclass
class DownloadSourceRegistry:
    sources: dict[str, DownloadSourceRecord] = field(default_factory=dict)

    def enabled(self) -> list[DownloadSourceRecord]:
        return sorted(self.sources.values(), key=lambda item: (-item.priority, item.source_id))

    def get(self, source_id: str) -> DownloadSourceRecord | None:
        return self.sources.get(source_id)

    def names(self) -> dict[str, str]:
        return {key: value.name for key, value in self.sources.items()}


def _manifest_paths(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return ()
    return sorted(root.glob("*/plugin.toml"))


def load_download_sources(
    client: httpx.AsyncClient,
    roots: Iterable[Path] | None = None,
    config: dict[str, Any] | None = None,
) -> DownloadSourceRegistry:
    configured = config or {}
    source_settings = {
        str(item.get("id")): item
        for item in configured.get("sources", [])
        if isinstance(item, dict) and item.get("id")
    }
    if roots is None:
        roots = [Path(__file__).resolve().parent]
    registry = DownloadSourceRegistry()
    for root in roots:
        for manifest_path in _manifest_paths(root):
            data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            source_id = str(data["id"])
            if source_id in registry.sources:
                continue
            settings = source_settings.get(source_id, {})
            if settings.get("enabled", True) is False:
                continue
            entrypoint = str(data.get("entrypoint", "source:create_source"))
            module_name, _, factory_name = entrypoint.partition(":")
            if not module_name or not factory_name:
                raise ValueError(f"{source_id}: invalid entrypoint")
            if root == Path(__file__).resolve().parent:
                package = f"app.download_sources.{manifest_path.parent.name}.{module_name}"
                module = importlib.import_module(package)
            else:
                module_path = manifest_path.parent / (module_name.replace(".", "/") + ".py")
                if not module_path.is_file():
                    raise ValueError(f"{source_id}: module not found: {module_path}")
                module_spec = importlib.util.spec_from_file_location(
                    f"musico_download_source_{source_id}", module_path
                )
                if module_spec is None or module_spec.loader is None:
                    raise ValueError(f"{source_id}: module not found")
                module = importlib.util.module_from_spec(module_spec)
                module_spec.loader.exec_module(module)
            factory = getattr(module, factory_name)
            config_schema = dict(data.get("config_schema") or {})
            source_config = {**config_schema, **(settings.get("config") or {})}
            if not _apply_env_overrides(
                source_id,
                settings,
                source_config,
                requires_base_url=bool(data.get("requires_base_url", False)),
            ):
                continue
            record = DownloadSourceRecord(
                source_id=source_id,
                name=str(settings.get("name") or data.get("name") or source_id),
                priority=int(settings.get("priority", data.get("priority", 0))),
                hosts=_merged_hosts(data.get("hosts", []), settings, source_config),
                config_schema=config_schema,
                source=factory(client, source_config),
            )
            registry.sources[source_id] = record
            log.info("download_source_loaded", source_id=source_id)
    return registry


def _apply_env_overrides(
    source_id: str,
    settings: dict[str, Any],
    source_config: dict[str, Any],
    *,
    requires_base_url: bool = False,
) -> bool:
    """Resolve the indirect ``*_env`` references from the YAML config.

    Environment variable names are declared in exactly one place
    (``configs/download_sources.yaml``); plugins only state whether they
    need an address.  Returns False when a source requires a base URL but
    none is configured, so that source is skipped instead of failing the
    whole registry.
    """
    variable = str(source_config.pop("base_url_env", "") or "").strip()
    if variable:
        resolved = os.environ.get(variable, "").strip()
        if resolved:
            source_config.setdefault("base_url", resolved)
    if requires_base_url and not str(source_config.get("base_url") or "").strip():
        log.warning(
            "download_source_missing_base_url",
            source_id=source_id,
            env=variable or None,
        )
        return False
    hosts_variable = str(source_config.pop("hosts_env", "") or "").strip()
    if hosts_variable:
        extra = [
            item.strip().lower()
            for item in os.environ.get(hosts_variable, "").split(",")
            if item.strip()
        ]
        if extra:
            configured = settings.get("hosts")
            settings["hosts"] = list(configured if isinstance(configured, list) else []) + extra
    return True


def _merged_hosts(
    manifest_hosts: object,
    settings: dict[str, Any],
    source_config: dict[str, Any],
) -> tuple[str, ...]:
    hosts: list[str] = []
    for group in (manifest_hosts, settings.get("hosts")):
        if not isinstance(group, list):
            continue
        hosts.extend(str(item).lower().rstrip(".") for item in group if str(item).strip())
    base_url = str(source_config.get("base_url") or "").strip()
    if base_url:
        hostname = (urlparse(base_url).hostname or "").lower().rstrip(".")
        if hostname:
            hosts.append(hostname)
            if hostname.startswith("www."):
                hosts.append(hostname.removeprefix("www."))
    return tuple(dict.fromkeys(item for item in hosts if item))

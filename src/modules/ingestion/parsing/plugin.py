# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Plugin system for source parsers.

This module provides a plugin-based architecture for source parsers,
allowing dynamic loading of custom parsers without modifying core code.

Trust boundary: plugins are executed with full process privileges
(``spec.loader.exec_module``) and no integrity verification. Plugin files
are part of the trusted deployment artifact — only operators with
filesystem write access to the plugin directory can install them, and such
access already implies full code execution. Untrusted parties must never
be able to write there.

Usage:
    1. Create a parser class inheriting from BaseSourceParser
    2. Decorate with @source_parser_plugin or create a plugin entry point
    3. The registry will automatically discover and load the parser

Example plugin:

    from modules.ingestion.parsing.base import BaseSourceParser
    from modules.ingestion.domain.models import NewsItem, SourceConfig
    from modules.ingestion.parsing.plugin import source_parser_plugin

    @source_parser_plugin(name="custom_parser", version="1.0.0")
    class CustomParser(BaseSourceParser):
        async def parse(self, config: SourceConfig) -> list[NewsItem]:
            # Your parsing logic here
            pass
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from core.observability import get_logger

if TYPE_CHECKING:
    from modules.ingestion.parsing.base import BaseSourceParser

log = get_logger(__name__)


@dataclass
class PluginMetadata:
    """Metadata for a source parser plugin."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    supported_types: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)


# Global plugin registry
_plugin_registry: dict[str, tuple[BaseSourceParser, PluginMetadata]] = {}


def source_parser_plugin(
    name: str,
    version: str = "1.0.0",
    description: str = "",
    author: str = "",
    supported_types: list[str] | None = None,
    capabilities: list[str] | None = None,
) -> Callable:
    """Define decorator to register a source parser as a plugin.

    Args:
        name: Unique plugin name.
        version: Plugin version string.
        description: Human-readable description.
        author: Plugin author.
        supported_types: List of source types this parser supports.
        capabilities: List of capabilities (e.g., ["incremental", "streaming"]).

    Returns:
        Decorator function.

    Example:
        @source_parser_plugin(
            name="my_parser",
            supported_types=["custom_rss", "custom_xml"],
            capabilities=["incremental"]
        )
        class MyParser(BaseSourceParser):
            ...
    """

    def decorator(cls: type) -> type:
        metadata = PluginMetadata(
            name=name,
            version=version,
            description=description,
            author=author,
            supported_types=supported_types or [],
            capabilities=capabilities or [],
        )
        _plugin_registry[name] = (cls, metadata)
        log.debug("plugin_registered", name=name, version=version)
        return cls

    return decorator


def get_registered_plugins() -> dict[str, PluginMetadata]:
    """Get all registered plugin metadata.

    Returns:
        Dictionary mapping plugin names to their metadata.
    """
    return {name: meta for name, (_, meta) in _plugin_registry.items()}


def get_plugin(name: str) -> tuple[BaseSourceParser, PluginMetadata] | None:
    """Get a registered plugin by name.

    Args:
        name: Plugin name.

    Returns:
        Tuple of (parser_class, metadata) or None if not found.
    """
    return _plugin_registry.get(name)


def discover_plugins_from_directory(directory: str | Path) -> list[str]:
    """Discover and load plugins from a directory.

    Looks for Python files that register parsers via the
    @source_parser_plugin decorator at import time.

    Trust boundary: every ``.py`` file under ``directory`` is executed as
    arbitrary Python code. The directory must be provisioned by the
    operator (e.g. ``WEAVER_SOURCE_PLUGINS``) — treat it with the same
    trust level as the application code itself; never point it at a
    user-writable location.

    Module names embed a hash of the resolved file path, so files with
    the same stem in different directories cannot collide in
    ``sys.modules``, and re-scanning the same directory is idempotent
    (already-imported modules are not re-executed).

    Args:
        directory: Path to the plugins directory.

    Returns:
        List of successfully loaded plugin names.
    """
    if isinstance(directory, str):
        directory = Path(directory)

    if not directory.exists() or not directory.is_dir():
        log.warning("plugin_directory_not_found", path=str(directory))
        return []

    loaded_plugins = []
    plugin_paths = list(directory.glob("*.py"))

    for plugin_path in plugin_paths:
        if plugin_path.name.startswith("_"):
            continue

        try:
            resolved = plugin_path.resolve()
            path_hash = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
            module_name = f"weaver_source_plugins.{plugin_path.stem}_{path_hash}"
            if module_name in sys.modules:
                # Already imported (e.g. repeated scan) — do not re-execute.
                loaded_plugins.append(module_name)
                continue
            spec = importlib.util.spec_from_file_location(module_name, resolved)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                before = set(_plugin_registry.keys())
                spec.loader.exec_module(module)

                # A module counts as loaded only if it actually registered
                # at least one plugin via @source_parser_plugin at import
                # time. A bare create_parser() factory is never invoked, so
                # reporting such a module as loaded would be misleading.
                if set(_plugin_registry.keys()) - before:
                    loaded_plugins.append(module_name)
                    log.info("plugin_loaded", path=str(plugin_path))
                else:
                    log.warning(
                        "plugin_module_registered_nothing",
                        path=str(plugin_path),
                    )

        except Exception as exc:
            log.error(
                "plugin_load_failed",
                path=str(plugin_path),
                error=str(exc),
            )

    return loaded_plugins


def discover_plugins_from_entry_points() -> list[str]:
    """Discover plugins via setuptools entry_points.

    Looks for entry points in the 'weaver_source_parsers' group.

    Returns:
        List of discovered plugin names.
    """
    loaded_plugins = []

    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        source_eps = eps.get("weaver_source_parsers", [])

        for ep in source_eps:
            try:
                plugin_class = ep.load()
                if callable(plugin_class):
                    loaded_plugins.append(ep.name)
                    log.info("entry_point_plugin_loaded", name=ep.name)
                else:
                    log.warning(
                        "invalid_plugin_entry_point",
                        name=ep.name,
                        reason="No callable found",
                    )
            except Exception as exc:
                log.error(
                    "entry_point_load_failed",
                    name=ep.name,
                    error=str(exc),
                )

    except ImportError:
        log.debug("importlib_metadata_not_available")

    return loaded_plugins


def scan_and_load_external_plugins(config_paths: list[str] | None = None) -> None:
    """Scan configured paths and load external plugins.

    Args:
        config_paths: List of directory paths to scan for plugins.
                      Defaults to WEAVER_SOURCE_PLUGINS env var paths.
    """
    paths_to_scan = []

    if config_paths:
        paths_to_scan = config_paths
    else:
        env_paths = os.environ.get("WEAVER_SOURCE_PLUGINS", "")
        if env_paths:
            paths_to_scan = env_paths.split(os.pathsep)

    for path in paths_to_scan:
        discovered = discover_plugins_from_directory(path)
        if discovered:
            log.info("external_plugins_loaded", path=path, count=len(discovered))


def load_plugins(plugin_paths: list[str] | None = None) -> list[str]:
    """Load external parser plugins.

    Args:
        plugin_paths: Optional list of directory paths to scan.

    Returns:
        Names of plugins newly registered by this call (not the full
        set of already-registered core plugins).
    """
    before = set(get_registered_plugins().keys())
    scan_and_load_external_plugins(plugin_paths)
    return sorted(set(get_registered_plugins().keys()) - before)

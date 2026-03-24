# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Plugin system for source parsers.

This module provides a plugin-based architecture for source parsers,
allowing dynamic loading of custom parsers without modifying core code.

Usage:
    1. Create a parser class inheriting from BaseSourceParser
    2. Decorate with @source_parser_plugin or create a plugin entry point
    3. The registry will automatically discover and load the parser

Example plugin:

    from modules.source.base import BaseSourceParser
    from modules.source.models import NewsItem, SourceConfig
    from modules.source.plugin import source_parser_plugin

    @source_parser_plugin(name="custom_parser", version="1.0.0")
    class CustomParser(BaseSourceParser):
        async def parse(self, config: SourceConfig) -> list[NewsItem]:
            # Your parsing logic here
            pass
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from modules.source.base import BaseSourceParser

log = logging.getLogger("source_plugin")


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
_plugin_registry: dict[str, tuple["BaseSourceParser", PluginMetadata]] = {}
_plugin_decorators: dict[str, Callable] = {}


def source_parser_plugin(
    name: str,
    version: str = "1.0.0",
    description: str = "",
    author: str = "",
    supported_types: list[str] | None = None,
    capabilities: list[str] | None = None,
) -> Callable:
    """Decorator to register a source parser as a plugin.

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
        _plugin_decorators[name] = decorator
        log.debug("plugin_registered", name=name, version=version)
        return cls

    return decorator


def get_registered_plugins() -> dict[str, PluginMetadata]:
    """Get all registered plugin metadata.

    Returns:
        Dictionary mapping plugin names to their metadata.
    """
    return {name: meta for name, (_, meta) in _plugin_registry.items()}


def get_plugin(name: str) -> tuple["BaseSourceParser", PluginMetadata] | None:
    """Get a registered plugin by name.

    Args:
        name: Plugin name.

    Returns:
        Tuple of (parser_class, metadata) or None if not found.
    """
    return _plugin_registry.get(name)


def discover_plugins_from_directory(directory: str | Path) -> list[str]:
    """Discover and load plugins from a directory.

    Looks for Python files with a `create_parser` function or classes
    decorated with @source_parser_plugin.

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
            module_name = f"weaver_source_plugins.{plugin_path.stem}"
            spec = importlib.util.spec_from_file_location(module_name, plugin_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                if module_name in _plugin_registry or hasattr(module, "create_parser"):
                    loaded_plugins.append(module_name)
                    log.info("plugin_loaded", path=str(plugin_path))

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
                if hasattr(plugin_class, "__call__"):
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

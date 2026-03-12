"""TOML Prompt loader with caching and versioning."""

from __future__ import annotations

import tomllib
from pathlib import Path

from core.observability.logging import get_logger

log = get_logger("prompt_loader")


class PromptLoader:
    """Loads prompt templates from TOML files with in-memory caching.

    Each TOML file contains a `version` key and prompt content
    under named keys (e.g. 'system', 'user').

    Args:
        path: Directory path containing prompt TOML files.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._cache: dict[str, dict] = {}

    def get(self, name: str, key: str = "system") -> str:
        """Get a prompt template by name and key.

        Args:
            name: Prompt file name (without .toml extension).
            key: Key within the TOML file (default: 'system').

        Returns:
            The prompt template string.

        Raises:
            FileNotFoundError: If the TOML file doesn't exist.
            KeyError: If the key doesn't exist in the TOML file.
        """
        if name not in self._cache:
            toml_path = self._path / f"{name}.toml"
            with open(toml_path, "rb") as f:
                self._cache[name] = tomllib.load(f)
            log.debug("prompt_loaded", name=name, path=str(toml_path))

        return self._cache[name][key]

    def get_version(self, name: str) -> str:
        """Get the version of a prompt template.

        Args:
            name: Prompt file name (without .toml extension).

        Returns:
            Version string, or 'unknown' if not set.
        """
        if name not in self._cache:
            self.get(name)
        return self._cache[name].get("version", "unknown")

    def reload(self, name: str | None = None) -> None:
        """Reload prompt templates from disk.

        Args:
            name: Specific prompt to reload. If None, clears all cache.
        """
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()
        log.info("prompts_reloaded", name=name or "all")

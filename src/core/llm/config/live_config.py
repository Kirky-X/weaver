# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Live configuration hot-reload for LLM module.

Watches config/llm.toml for changes and atomically swaps
the in-memory configuration without service restart.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.llm.config.config import LLMSettings
from core.observability.logging import get_logger

log = get_logger("live_config")

if TYPE_CHECKING:
    pass


class ConfigReloadError(Exception):
    """Configuration reload failed."""

    def __init__(self, message: str, validation_errors: list[str] | None = None) -> None:
        self.message = message
        self.validation_errors = validation_errors or []
        super().__init__(message)


class LiveConfig:
    """Hot-reload manager for LLM configuration.

    Watches config/llm.toml for changes using watchfiles,
    validates the new configuration, and atomically swaps
    the in-memory reference.

    Usage:
        live = LiveConfig(llm_toml_path)
        await live.start(on_reload=my_callback)
        # ... later ...
        await live.stop()
    """

    def __init__(
        self,
        config_path: str | Path,
    ) -> None:
        """Initialize the live config manager.

        Args:
            config_path: Path to the LLM TOML configuration file.
        """
        self._path = Path(config_path)
        self._current: LLMSettings | None = None
        self._watcher_task: asyncio.Task[None] | None = None
        self._running = False
        self._on_reload: Callable[[LLMSettings], Coroutine[Any, Any, None]] | None = None

        # Load initial configuration
        self._current = self._load_and_validate()

    @property
    def settings(self) -> LLMSettings:
        """Get the current active configuration.

        Raises:
            RuntimeError: If configuration has not been loaded.
        """
        if self._current is None:
            raise RuntimeError("LiveConfig not initialized")
        return self._current

    async def start(
        self,
        on_reload: Callable[[LLMSettings], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Start watching the configuration file for changes.

        Args:
            on_reload: Optional callback invoked with the new LLMSettings
                after a successful reload.
        """
        if self._running:
            return

        self._on_reload = on_reload
        self._running = True
        self._watcher_task = asyncio.create_task(
            self._watch_loop(),
            name="live_config_watcher",
        )
        log.info("live_config_started", path=str(self._path))

    async def stop(self) -> None:
        """Stop watching the configuration file."""
        self._running = False
        if self._watcher_task:
            self._watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher_task
            self._watcher_task = None
        log.info("live_config_stopped")

    def reload(self) -> LLMSettings:
        """Manually reload the configuration.

        Returns:
            The new LLMSettings if reload succeeded, or the current one if failed.

        Raises:
            ConfigReloadError: If the new configuration is invalid.
        """
        new_settings = self._load_and_validate()
        if new_settings is None:
            raise ConfigReloadError("Configuration reload failed, keeping current config")

        old_settings = self._current
        self._current = new_settings
        log.info("live_config_reloaded", path=str(self._path))
        return new_settings

    async def _watch_loop(self) -> None:
        """Watch for file changes and reload."""
        try:
            from watchfiles import awatch
        except ImportError:
            log.warning("watchfiles_not_installed", msg="Hot-reload disabled. Install watchfiles.")
            return

        while self._running:
            try:
                async for changes in awatch(
                    self._path,
                    stop_event=asyncio.Event() if not self._running else None,
                    debounce_ms=500,
                    step=500,
                ):
                    if not self._running:
                        break

                    log.info("live_config_file_changed", path=str(self._path))
                    new_settings = self._load_and_validate()

                    if new_settings is not None and self._current is not None:
                        old_settings = self._current
                        self._current = new_settings
                        log.info("live_config_reloaded", path=str(self._path))

                        if self._on_reload:
                            try:
                                await self._on_reload(new_settings)
                            except Exception as exc:
                                log.error(
                                    "live_config_reload_callback_error",
                                    error=str(exc),
                                )
                    else:
                        log.warning(
                            "live_config_reload_failed",
                            path=str(self._path),
                            msg="Invalid configuration, keeping current",
                        )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("live_config_watch_error", error=str(exc))
                await asyncio.sleep(5)

    def _load_and_validate(self) -> LLMSettings | None:
        """Load and validate configuration from TOML file.

        Returns:
            LLMSettings if valid, None if invalid.
        """
        try:
            settings = LLMSettings()
            log.debug("live_config_validated", path=str(self._path))
            return settings
        except Exception as exc:
            log.error(
                "live_config_validation_failed",
                path=str(self._path),
                error=str(exc),
            )
            return None

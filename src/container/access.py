# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Thread-safe global access to Container and Settings instances."""

from __future__ import annotations

import threading

from config.settings import Settings
from container.container import Container

# Global container instance with thread-safe access
_container: Container | None = None
_container_lock = threading.Lock()

# Settings instance with thread-safe access
_settings_instance: Settings | None = None
_settings_lock = threading.Lock()


def get_container() -> Container:
    """Get the global container instance (thread-safe)."""
    with _container_lock:
        if _container is None:
            raise RuntimeError("Container not initialized. Create it in main.py first.")
        return _container


def set_container(container: Container) -> None:
    """Set the global container instance (thread-safe)."""
    global _container
    with _container_lock:
        _container = container


def get_settings() -> Settings:
    """Get settings instance (thread-safe)."""
    global _settings_instance
    with _settings_lock:
        if _settings_instance is None:
            from config.settings import Settings

            _settings_instance = Settings()
        return _settings_instance


def set_settings(settings: Settings) -> None:
    """Set settings instance (thread-safe)."""
    global _settings_instance
    with _settings_lock:
        _settings_instance = settings


def reset_container() -> None:
    """Reset global container to None (thread-safe). For testing and shutdown."""
    global _container
    with _container_lock:
        _container = None


def reset_settings() -> None:
    """Reset global settings to None (thread-safe). For testing and reconfiguration."""
    global _settings_instance
    with _settings_lock:
        _settings_instance = None

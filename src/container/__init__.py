# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Dependency injection container package.

Public API:
- Container: DI container facade combining lifecycle, pools, services, search mixins
- get_container / set_container: Thread-safe global container access
- reset_container: Reset the global container (testing / shutdown)
- get_settings / set_settings: Thread-safe global settings access
- reset_settings: Reset the global settings instance (testing / shutdown)
"""

from container.access import (
    get_container,
    get_settings,
    reset_container,
    reset_settings,
    set_container,
    set_settings,
)
from container.container import Container

__all__ = [
    "Container",
    "get_container",
    "get_settings",
    "reset_container",
    "reset_settings",
    "set_container",
    "set_settings",
]

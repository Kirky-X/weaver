# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Dependency injection container package.

Public API:
- Container: DI container facade combining lifecycle, pools, services, search mixins
- get_container / set_container: Thread-safe global container access
- get_settings / set_settings: Thread-safe global settings access
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

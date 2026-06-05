# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Alias module for dependency registry.

This module provides backward compatibility for imports expecting
api.endpoints._deps.Endpoints.
"""

from api.endpoints.deps_registry import Endpoints

__all__ = ["Endpoints"]

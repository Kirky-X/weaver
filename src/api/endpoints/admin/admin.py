# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared helpers for admin API endpoints.

Endpoint implementations have been split into domain-specific modules:
- authorities.py: source authority management
- llm_monitoring.py: LLM failure/usage monitoring
- articles.py: article operations
- memory.py: memory system diagnostics
- api_keys.py: API key management

This module retains shared dependency helpers used across those modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.dependencies import get_container
from core.observability import get_logger

if TYPE_CHECKING:
    from modules.analytics import LLMFailureRepo, LLMUsageRepo

log = get_logger("admin_api")


# Lazy import wrappers to avoid circular dependency
def _get_container():
    """Get the application container."""
    return get_container()


def _get_source_authority_repo():
    """Get the source authority repository."""
    container = get_container()
    return container.source_authority_repo()


def llm_failure_repo() -> LLMFailureRepo:
    """Get the LLM failure repo instance."""
    container = get_container()
    return container.llm_failure_repo()


def get_llm_usage_repo() -> LLMUsageRepo:
    """Get the LLM usage repo instance."""
    container = get_container()
    return container.llm_usage_repo()

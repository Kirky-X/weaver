# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared graph metrics utilities for graph and monitoring endpoints."""

from __future__ import annotations

# Cache key and TTL for full metrics view
GRAPH_METRICS_FULL_CACHE_KEY = "cache:graph_metrics:full"
GRAPH_METRICS_CACHE_TTL = 300  # 5 minutes


def parse_include_param(include: str | None) -> set[str] | None:
    """Parse the include query parameter.

    Returns:
        - None if include is None or 'all' (include everything)
        - Set of specific includes otherwise

    """
    if include is None or include.lower() == "all":
        return None
    return {item.strip().lower() for item in include.split(",")}


def should_include(item: str, include_set: set[str] | None) -> bool:
    """Check if an item should be included based on include_set.

    Args:
        item: The item to check
        include_set: Set of includes, or None for all

    Returns:
        True if item should be included

    """
    if include_set is None:
        return True
    return item.lower() in include_set

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared graph metrics utilities for graph and monitoring endpoints.

The health-summary and full-metrics view implementations live here once;
``api/endpoints/graph/graph_metrics.py`` (public API) and
``api/endpoints/monitoring/graph.py`` (admin monitoring) register thin
routing shells over them. Response model classes stay per-endpoint on
purpose: the monitoring variants round floats to 2 decimals
(RoundedFloat) while the public API returns full-precision floats, and
the monitoring view translates relationship types to Chinese.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from api.schemas.response import success_response
from core.observability import get_logger
from modules.knowledge.graph import GraphQualityMetrics

if TYPE_CHECKING:
    from core.protocols import CachePool, GraphPool

log = get_logger(__name__)

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
    # An empty `?include=` must behave like no filter, not an unmatchable {""}.
    parsed = {item.strip().lower() for item in include.split(",") if item.strip()}
    return parsed or None


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


async def get_health_summary_view(
    graph_pool: GraphPool,
    model_cls: type[Any],
    *,
    db_type: str | None = None,
) -> Any:
    """Build the health-summary view payload.

    Args:
        graph_pool: Graph database pool.
        model_cls: Endpoint-specific response model (field sets are identical;
            only float rounding differs between the two endpoints).
        db_type: Graph backend type passed through to GraphQualityMetrics;
            None lets the metrics class apply its own default.

    Returns:
        success_response wrapping model_cls.

    """
    metrics = (
        GraphQualityMetrics(graph_pool)
        if db_type is None
        else GraphQualityMetrics(graph_pool, db_type=db_type)
    )
    summary = await metrics.get_health_summary()

    return success_response(
        model_cls(
            health_score=summary["health_score"],
            status=summary["status"],
            entity_count=summary["entity_count"],
            relationship_count=summary["relationship_count"],
            orphan_ratio=summary["orphan_ratio"],
            connectedness=summary["connectedness"],
            average_degree=summary["average_degree"],
            recommendations=summary["recommendations"],
        )
    )


async def get_full_metrics_view(
    graph_pool: GraphPool,
    include: str | None,
    cache: CachePool | None,
    model_cls: type[Any],
    *,
    db_type: str | None = None,
    rel_type_map: dict[str, str] | None = None,
) -> Any:
    """Build the full metrics view with optional caching and include filtering.

    Args:
        graph_pool: Graph database pool.
        include: Raw include query parameter (parsed via parse_include_param).
        cache: Optional cache pool; when present and no include filter is set,
            the full payload is served from / written to the shared cache key.
        model_cls: Endpoint-specific response model (see get_health_summary_view).
        db_type: Graph backend type; None uses the metrics class default.
        rel_type_map: Optional relationship-type translation applied to
            relationship_type_distribution keys (monitoring uses a zh map).

    """
    include_set = parse_include_param(include)

    if cache and include_set is None:
        try:
            cached = await cache.get(GRAPH_METRICS_FULL_CACHE_KEY)
            if cached:
                cached_data = json.loads(cached)
                return success_response(model_cls(**cached_data))
        except Exception as exc:
            log.warning("cache_lookup_failed", error=str(exc))  # Fall through to compute

    metrics = (
        GraphQualityMetrics(graph_pool)
        if db_type is None
        else GraphQualityMetrics(graph_pool, db_type=db_type)
    )
    result = await metrics.calculate_all_metrics(include=include_set)

    raw_rel_types = (
        result.relationship_type_distribution
        if should_include("distributions", include_set)
        else {}
    )
    if rel_type_map:
        rel_types = {rel_type_map.get(k, k): v for k, v in raw_rel_types.items()}
    else:
        rel_types = raw_rel_types

    response_data = model_cls(
        total_entities=result.total_entities,
        total_articles=result.total_articles,
        total_relationships=result.total_relationships,
        total_mentions=result.total_mentions,
        # Guarded fields report null instead of the dataclass default (0)
        # when the include filter skipped their computation.
        connected_components=(
            result.connected_components if should_include("components", include_set) else None
        ),
        largest_component_size=(
            result.largest_component_size if should_include("components", include_set) else None
        ),
        average_degree=result.average_degree,
        modularity_score=(
            result.modularity_score if should_include("modularity", include_set) else None
        ),
        orphan_entities=(
            result.orphan_entities if should_include("orphans", include_set) else None
        ),
        high_degree_entities=(
            result.high_degree_entities if should_include("high_degree", include_set) else []
        ),
        entity_type_distribution=(
            result.entity_type_distribution if should_include("distributions", include_set) else {}
        ),
        relationship_type_distribution=rel_types,
        computed_at=result.computed_at.isoformat(),
    )

    if cache and include_set is None:
        try:
            await cache.set(
                GRAPH_METRICS_FULL_CACHE_KEY,
                json.dumps(response_data.model_dump()),
                ex=GRAPH_METRICS_CACHE_TTL,
            )
        except Exception as exc:
            log.warning("cache_write_failed", error=str(exc))  # Cache failure is not critical

    return success_response(response_data)

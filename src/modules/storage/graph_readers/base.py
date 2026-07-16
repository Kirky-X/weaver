# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Base class for graph readers with shared dependencies.

Provides common dependency injection (pool, query_builder, execute_fn) for
all graph reader subclasses. The fallback-aware query execution is delegated
to the owning GraphRepository via the injected ``execute_fn`` callable, so
the fallback pool state stays centralized.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from core.db.graph_query_builders import GraphQueryBuilder

if TYPE_CHECKING:
    from core.protocols import GraphPool

# Callable signature: (build_query_fn, params) -> list[dict[str, Any]]
# where build_query_fn: (GraphQueryBuilder) -> str
ExecuteWithFallbackFn = Callable[..., Any]


class GraphReaderBase:
    """Base class for graph readers.

    Holds the shared dependencies required by all reader subclasses:
    the graph pool, the database-specific query builder, and a callable
    that executes a query with automatic fallback to the secondary pool.

    Args:
        pool: Primary graph database pool (Neo4j or LadybugDB).
        query_builder: Database-specific query builder for primary.
        execute_fn: Callable that runs a query with fallback support.
            Signature matches ``GraphRepository._execute_with_fallback``.
    """

    def __init__(
        self,
        pool: GraphPool,
        query_builder: GraphQueryBuilder,
        execute_fn: ExecuteWithFallbackFn,
    ) -> None:
        self._pool = pool
        self._query_builder = query_builder
        self._execute_fn = execute_fn

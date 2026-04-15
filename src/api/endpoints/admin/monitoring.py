# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Database monitoring endpoints for performance analysis.

Provides admin endpoints for:
- Index usage statistics
- Table size and row counts
- Connection pool status
- Slow query analysis (requires pg_stat_statements)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from api.dependencies import get_container
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response
from core.db.postgres import PostgresPool

if TYPE_CHECKING:
    from container import Container

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


class IndexStats(BaseModel):
    """Index usage statistics."""

    table: str = Field(..., description="Table name")
    index: str = Field(..., description="Index name")
    scans: int = Field(..., description="Number of index scans")
    tuples_read: int = Field(..., description="Tuples read via index")
    tuples_fetched: int = Field(..., description="Tuples fetched via index")
    size: str = Field(..., description="Index size (human-readable)")


class TableStats(BaseModel):
    """Table statistics."""

    table: str = Field(..., description="Table name")
    rows: int = Field(..., description="Estimated row count")
    size: str = Field(..., description="Table size (human-readable)")
    index_size: str = Field(..., description="Total index size")


class PoolStats(BaseModel):
    """Connection pool statistics."""

    pool_size: int = Field(..., description="Current pool size")
    checked_in: int = Field(..., description="Available connections")
    checked_out: int = Field(..., description="Active connections")
    overflow: int = Field(..., description="Overflow connections")


@router.get("/database/indexes", response_model=APIResponse[list[IndexStats]])
async def get_index_usage(
    limit: int = Query(50, ge=1, le=200, description="Max indexes to return"),
    _: str = Depends(verify_admin_api_key),
    container: Container = Depends(get_container),
) -> APIResponse[list[IndexStats]]:
    """Get PostgreSQL index usage statistics.

    Returns information about:
    - Index scan counts
    - Index size
    - Unused indexes (candidates for removal)

    Args:
        limit: Maximum number of indexes to return.
        _: Admin API key verification.
        container: Application container.

    Returns:
        List of index statistics ordered by scan count (ascending).

    """
    pool = container.relational_pool()

    # Only works with PostgreSQL
    if container.relational_pool_type != "postgresql":
        return success_response(
            [],
            message="Index statistics only available for PostgreSQL",
        )

    assert isinstance(pool, PostgresPool)

    async with pool.session() as session:
        result = await session.execute(
            text("""
                SELECT
                    schemaname || '.' || relname AS table,
                    indexrelname AS index,
                    idx_scan AS scans,
                    idx_tup_read AS tuples_read,
                    idx_tup_fetch AS tuples_fetched,
                    pg_size_pretty(pg_relation_size(indexrelid)) AS size
                FROM pg_stat_user_indexes
                ORDER BY idx_scan ASC
                LIMIT :limit
            """),
            {"limit": limit},
        )

        indexes = [
            IndexStats(
                table=row[0],
                index=row[1],
                scans=row[2] or 0,
                tuples_read=row[3] or 0,
                tuples_fetched=row[4] or 0,
                size=row[5],
            )
            for row in result
        ]

    return success_response(indexes)


@router.get("/database/tables", response_model=APIResponse[list[TableStats]])
async def get_table_stats(
    limit: int = Query(50, ge=1, le=200, description="Max tables to return"),
    _: str = Depends(verify_admin_api_key),
    container: Container = Depends(get_container),
) -> APIResponse[list[TableStats]]:
    """Get table size and row count statistics.

    Args:
        limit: Maximum number of tables to return.
        _: Admin API key verification.
        container: Application container.

    Returns:
        List of table statistics ordered by size (descending).

    """
    pool = container.relational_pool()

    if container.relational_pool_type != "postgres":
        return success_response(
            [],
            message="Table statistics only available for PostgreSQL",
        )

    assert isinstance(pool, PostgresPool)

    async with pool.session() as session:
        result = await session.execute(
            text("""
                SELECT
                    schemaname || '.' || relname AS table,
                    n_live_tup AS rows,
                    pg_size_pretty(pg_total_relation_size(c.oid)) AS size,
                    pg_size_pretty(pg_indexes_size(c.oid)) AS index_size
                FROM pg_stat_user_tables t
                JOIN pg_class c ON c.relname = t.relname
                ORDER BY pg_total_relation_size(c.oid) DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )

        tables = [
            TableStats(
                table=row[0],
                rows=row[1] or 0,
                size=row[2],
                index_size=row[3],
            )
            for row in result
        ]

    return success_response(tables)


@router.get("/database/pool", response_model=APIResponse[PoolStats])
async def get_pool_stats(
    _: str = Depends(verify_admin_api_key),
    container: Container = Depends(get_container),
) -> APIResponse[PoolStats]:
    """Get database connection pool statistics.

    Args:
        _: Admin API key verification.
        container: Application container.

    Returns:
        Connection pool statistics.

    """
    pool = container.relational_pool()

    # Get pool statistics from SQLAlchemy
    if container.relational_pool_type == "postgresql":
        assert isinstance(pool, PostgresPool)
        engine = pool._engine
        if engine is None:
            return success_response(PoolStats(pool_size=0, checked_in=0, checked_out=0, overflow=0))

        pool_obj = engine.sync_engine.pool
        status = pool_obj.status()

        return success_response(
            PoolStats(
                pool_size=status.size,
                checked_in=status.checkedin,
                checked_out=status.checkedout,
                overflow=status.overflow,
            )
        )

    # DuckDB doesn't have connection pool
    return success_response(
        PoolStats(pool_size=1, checked_in=1, checked_out=0, overflow=0),
        message="DuckDB uses single connection, no pool statistics",
    )


@router.get("/database/slow-queries")
async def get_slow_queries(
    limit: int = Query(20, ge=1, le=100, description="Max queries to return"),
    _: str = Depends(verify_admin_api_key),
    container: Container = Depends(get_container),
) -> APIResponse:
    """Get recent slow queries from pg_stat_statements.

    Requires pg_stat_statements extension to be enabled in PostgreSQL.

    Args:
        limit: Maximum number of queries to return.
        _: Admin API key verification.
        container: Application container.

    Returns:
        List of slow queries ordered by average duration.

    """
    pool = container.relational_pool()

    if container.relational_pool_type != "postgres":
        return success_response(
            {"slow_queries": []},
            message="Slow query statistics only available for PostgreSQL",
        )

    assert isinstance(pool, PostgresPool)

    try:
        async with pool.session() as session:
            result = await session.execute(
                text("""
                    SELECT
                        query,
                        calls,
                        mean_exec_time AS avg_duration_ms,
                        total_exec_time AS total_duration_ms,
                        rows AS rows_retrieved
                    FROM pg_stat_statements
                    WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
                    ORDER BY mean_exec_time DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            )

            queries = [
                {
                    "query": row[0][:200],  # Truncate long queries
                    "calls": row[1],
                    "avg_duration_ms": round(row[2] or 0, 2),
                    "total_duration_ms": round(row[3] or 0, 2),
                    "rows_retrieved": row[4] or 0,
                }
                for row in result
            ]

        return success_response({"slow_queries": queries, "limit": limit})

    except Exception as exc:
        return success_response(
            {"slow_queries": [], "error": str(exc)},
            message="pg_stat_statements not available. Enable with: CREATE EXTENSION pg_stat_statements;",
        )

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Database strategy factory for failover support.

Determines which database backends to use at startup time.
Tries primary databases (PostgreSQL, Neo4j) first, falls back to
embedded databases (DuckDB, LadybugDB) if unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.db.pool_protocols import GraphPool, RelationalPool
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from config.settings import DuckDBSettings, LadybugSettings, Neo4jSettings, PostgresSettings

log = get_logger("database_strategy")


@dataclass(frozen=True)
class DatabaseStrategy:
    """Immutable database strategy determined at startup.

    Contains the selected pool instances and their types.
    """

    relational_pool: RelationalPool
    graph_pool: GraphPool | None
    relational_type: str  # "postgresql" | "duckdb"
    graph_type: str  # "neo4j" | "ladybug" | "none"


async def create_strategy(
    pg_settings: PostgresSettings,
    neo4j_settings: Neo4jSettings,
    duckdb_settings: DuckDBSettings | None = None,
    ladybug_settings: LadybugSettings | None = None,
) -> DatabaseStrategy:
    """Create database strategy by trying primary then fallback databases.

    Args:
        pg_settings: PostgreSQL connection settings.
        neo4j_settings: Neo4j connection settings.
        duckdb_settings: DuckDB fallback settings.
        ladybug_settings: LadybugDB fallback settings.

    Returns:
        DatabaseStrategy with selected pools.
    """
    from core.db.duckdb_pool import DuckDBPool
    from core.db.ladybug_pool import LadybugPool
    from core.db.neo4j import Neo4jPool
    from core.db.postgres import PostgresPool
    from modules.storage.ladybug.schema import initialize_ladybug_schema

    # Default fallback settings
    if duckdb_settings is None:
        from config.settings import DuckDBSettings

        duckdb_settings = DuckDBSettings()
    if ladybug_settings is None:
        from config.settings import LadybugSettings

        ladybug_settings = LadybugSettings()

    # 1. Try PostgreSQL
    relational_pool: RelationalPool
    relational_type: str

    try:
        pg_pool = PostgresPool(
            dsn=pg_settings.dsn,
            pool_size=pg_settings.pool_size,
            max_overflow=pg_settings.max_overflow,
            pool_timeout=pg_settings.pool_timeout,
        )
        await pg_pool.startup()
        relational_pool = pg_pool
        relational_type = "postgresql"
        log.info("postgres_connected")
    except Exception as exc:
        log.warning("postgres_unavailable_fallback_to_duckdb", error=str(exc))
        if not duckdb_settings.enabled:
            raise RuntimeError("PostgreSQL unavailable and DuckDB fallback disabled") from exc

        # Fallback to DuckDB
        from modules.storage.duckdb.schema import initialize_duckdb_schema

        duckdb_pool = DuckDBPool(db_path=duckdb_settings.db_path)
        await duckdb_pool.startup()
        await initialize_duckdb_schema(duckdb_pool)
        relational_pool = duckdb_pool
        relational_type = "duckdb"
        log.info("duckdb_connected", db_path=duckdb_settings.db_path)

    # 2. Try Neo4j
    graph_pool: GraphPool | None = None
    graph_type: str = "none"

    if neo4j_settings.enabled:
        try:
            neo_pool = Neo4jPool(
                uri=neo4j_settings.uri,
                auth=(neo4j_settings.user, neo4j_settings.password),
            )
            await neo_pool.startup()
            graph_pool = neo_pool
            graph_type = "neo4j"
            log.info("neo4j_connected", uri=neo4j_settings.uri)
        except Exception as exc:
            log.warning("neo4j_unavailable_fallback_to_ladybug", error=str(exc))
            if not ladybug_settings.enabled:
                log.warning("ladybug_fallback_disabled")
            else:
                # Fallback to LadybugDB
                ladybug_pool = LadybugPool(db_path=ladybug_settings.db_path)
                await ladybug_pool.startup()
                # Initialize schema
                await initialize_ladybug_schema(ladybug_pool)
                graph_pool = ladybug_pool
                graph_type = "ladybug"
                log.info("ladybug_connected", db_path=ladybug_settings.db_path)
    else:
        log.info("neo4j_disabled")

    return DatabaseStrategy(
        relational_pool=relational_pool,
        graph_pool=graph_pool,
        relational_type=relational_type,
        graph_type=graph_type,
    )

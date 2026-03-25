# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Database initializer for automatic database creation and migration."""

from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass
from typing import Any

import asyncpg
from alembic import command
from alembic.config import Config

from core.observability.logging import get_logger

log = get_logger("db_initializer")

REQUIRED_TABLES = [
    "articles",
    "article_vectors",
    "entity_vectors",
    "source_authorities",
]


class DatabaseInitError(Exception):
    """Exception raised when database initialization fails.

    Attributes:
        message: Human-readable error message.
        details: Additional details about the failure.
        suggestions: List of suggested fixes.
    """

    def __init__(
        self,
        message: str,
        details: list[str] | None = None,
        suggestions: list[str] | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error message.
            details: Additional details about the failure.
            suggestions: List of suggested fixes.
        """
        super().__init__(message)
        self.message = message
        self.details = details or []
        self.suggestions = suggestions or []

    def __str__(self) -> str:
        """Return a formatted error message."""
        result = self.message
        if self.details:
            result += "\nDetails:\n  - " + "\n  - ".join(self.details)
        if self.suggestions:
            result += "\nSuggestions:\n  - " + "\n  - ".join(self.suggestions)
        return result


# Neo4j constraints required for the application
REQUIRED_NEO4J_CONSTRAINTS = [
    {
        "name": "entity_name_type_unique",
        "query": (
            """
            CREATE CONSTRAINT entity_name_type_unique IF NOT EXISTS
            FOR (e:Entity) REQUIRE (e.canonical_name, e.type) IS UNIQUE
        """
        ),
        "description": "Unique constraint on Entity canonical_name and type",
    },
    {
        "name": "article_url_unique",
        "query": (
            """
            CREATE CONSTRAINT article_url_unique IF NOT EXISTS
            FOR (a:Article) REQUIRE a.url IS UNIQUE
        """
        ),
        "description": "Unique constraint on Article url",
    },
]


@dataclass
class ParsedDSN:
    """Parsed DSN components."""

    driver: str
    user: str
    password: str
    host: str
    port: int
    database: str


def parse_dsn(dsn: str) -> ParsedDSN:
    """Parse PostgreSQL DSN into components.

    Args:
        dsn: PostgreSQL connection string.

    Returns:
        ParsedDSN with extracted components.

    Example:
        postgresql+asyncpg://user:pass@host:5432/dbname
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(dsn)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid DSN format: {dsn}")

    return ParsedDSN(
        driver=parsed.scheme,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/"),
    )


async def check_database_exists(parsed: ParsedDSN) -> bool:
    """Check if the target database exists.

    Args:
        parsed: Parsed DSN components.

    Returns:
        True if database exists, False otherwise.
    """
    conn = await asyncpg.connect(
        host=parsed.host,
        port=parsed.port,
        user=parsed.user,
        password=parsed.password,
        database="postgres",
    )
    try:
        result = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            parsed.database,
        )
        return result is not None
    finally:
        await conn.close()


async def create_database(parsed: ParsedDSN) -> None:
    """Create the target database.

    Args:
        parsed: Parsed DSN components.
    """
    conn = await asyncpg.connect(
        host=parsed.host,
        port=parsed.port,
        user=parsed.user,
        password=parsed.password,
        database="postgres",
    )
    try:
        await conn.execute(
            f'CREATE DATABASE "{parsed.database}" ' f"OWNER {parsed.user} " f"ENCODING 'UTF8'"
        )
        log.info("database_created", database=parsed.database)
    except asyncpg.DuplicateDatabaseError:
        log.debug("database_already_exists", database=parsed.database)
    except asyncpg.InsufficientPrivilegeError as e:
        log.error(
            "database_create_permission_denied",
            database=parsed.database,
            user=parsed.user,
            error=str(e) if e.args else "Insufficient privilege",
        )
        raise RuntimeError(
            f"Permission denied to create database '{parsed.database}'. "
            f"Please create it manually or grant CREATEDB privilege to user '{parsed.user}'."
        ) from e
    finally:
        await conn.close()


async def wait_for_postgres(parsed: ParsedDSN, timeout: float = 30.0) -> None:
    """Wait for PostgreSQL to be available.

    Args:
        parsed: Parsed DSN components.
        timeout: Maximum wait time in seconds.
    """
    start_time = asyncio.get_event_loop().time()
    while True:
        try:
            conn = await asyncpg.connect(
                host=parsed.host,
                port=parsed.port,
                user=parsed.user,
                password=parsed.password,
                database="postgres",
                timeout=5.0,
            )
            await conn.close()
            log.info("postgres_available", host=parsed.host, port=parsed.port)
            return
        except (TimeoutError, asyncpg.PostgresError, OSError) as e:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout:
                raise RuntimeError(
                    f"PostgreSQL not available after {timeout}s at {parsed.host}:{parsed.port}"
                ) from e
            log.debug(
                "postgres_unavailable",
                host=parsed.host,
                port=parsed.port,
                error=str(e),
                retry_in=2,
            )
            await asyncio.sleep(2)


def _run_migrations_sync(alembic_ini_path: str, script_location: str, dsn: str) -> None:
    """Run Alembic migrations synchronously (internal function).

    Args:
        alembic_ini_path: Path to alembic.ini file.
        script_location: Path to alembic scripts directory.
        dsn: Database connection string.
    """
    import traceback

    config = Config(alembic_ini_path)
    config.set_main_option("script_location", script_location)
    config.set_main_option("sqlalchemy.url", dsn)

    try:
        command.upgrade(config, "head")
        log.info("migrations_completed")
    except Exception as e:
        log.error("migration_sync_failed", error=str(e), traceback=traceback.format_exc())
        raise


def run_migrations(alembic_ini_path: str, script_location: str, dsn: str) -> None:
    """Run Alembic migrations to the latest revision.

    This function runs migrations in a separate thread to avoid
    conflicts with running event loops (e.g., in pytest-asyncio).

    Args:
        alembic_ini_path: Path to alembic.ini file.
        script_location: Path to alembic scripts directory.
        dsn: Database connection string.
    """
    try:
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                _run_migrations_sync,
                alembic_ini_path,
                script_location,
                dsn,
            )
            future.result()
    except RuntimeError:
        _run_migrations_sync(alembic_ini_path, script_location, dsn)
    except Exception as e:
        log.error("migration_failed", error=str(e))
        raise


async def verify_tables(dsn: str) -> bool:
    """Verify that all required tables exist.

    Args:
        dsn: Database connection string.

    Returns:
        True if all tables exist, False otherwise.
    """
    parsed = parse_dsn(dsn)
    conn = await asyncpg.connect(
        host=parsed.host,
        port=parsed.port,
        user=parsed.user,
        password=parsed.password,
        database=parsed.database,
    )
    try:
        existing_tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        existing = {row["tablename"] for row in existing_tables}
        missing = set(REQUIRED_TABLES) - existing

        if missing:
            log.warning("missing_tables", tables=list(missing))
            return False

        log.debug("all_tables_exist", tables=REQUIRED_TABLES)
        return True
    finally:
        await conn.close()


async def initialize_database(
    dsn: str,
    alembic_ini_path: str = "alembic.ini",
    script_location: str = "src/alembic",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Initialize database: create if not exists, run migrations.

    This is the main entry point for database initialization.

    Args:
        dsn: PostgreSQL connection string.
        alembic_ini_path: Path to alembic.ini file.
        script_location: Path to alembic scripts directory.
        timeout: Maximum wait time for PostgreSQL availability.

    Returns:
        Dict with initialization status and details.
    """
    result: dict[str, Any] = {
        "database_created": False,
        "migrations_run": False,
        "tables_verified": False,
    }

    parsed = parse_dsn(dsn)
    log.info(
        "database_initialization_start",
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    )

    await wait_for_postgres(parsed, timeout)

    db_exists = await check_database_exists(parsed)
    if not db_exists:
        log.info("database_not_found_creating", database=parsed.database)
        await create_database(parsed)
        result["database_created"] = True
    else:
        log.debug("database_exists", database=parsed.database)

    tables_ok = await verify_tables(dsn)
    if not tables_ok:
        log.info("running_migrations")
        run_migrations(alembic_ini_path, script_location, dsn)
        result["migrations_run"] = True

        tables_ok = await verify_tables(dsn)
        if not tables_ok:
            raise RuntimeError("Tables still missing after migration")

    result["tables_verified"] = tables_ok

    log.info("database_initialization_complete", **result)
    return result


async def _diagnose_missing_tables(dsn: str) -> dict[str, Any]:
    """Diagnose why required tables might be missing.

    This function provides detailed diagnostics when table verification fails,
    including checking for common issues like missing migrations or
    incorrect schema.

    Args:
        dsn: Database connection string.

    Returns:
        Dict with diagnostic information including:
        - existing_tables: List of tables that exist
        - missing_tables: List of required tables that are missing
        - alembic_version: Current alembic revision (if any)
        - suggestions: List of suggested fixes
    """
    parsed = parse_dsn(dsn)
    conn = await asyncpg.connect(
        host=parsed.host,
        port=parsed.port,
        user=parsed.user,
        password=parsed.password,
        database=parsed.database,
    )

    try:
        # Get existing tables
        existing_tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        existing = {row["tablename"] for row in existing_tables}
        missing = set(REQUIRED_TABLES) - existing

        # Check alembic version
        alembic_version = None
        try:
            version_row = await conn.fetchrow("SELECT version_num FROM alembic_version LIMIT 1")
            if version_row:
                alembic_version = version_row["version_num"]
        except asyncpg.UndefinedTableError:
            pass  # alembic_version table doesn't exist

        # Generate suggestions
        suggestions = []
        if not existing:
            suggestions.append("Run database migrations: alembic upgrade head")
            suggestions.append("Check if alembic.ini is correctly configured")
        elif missing:
            suggestions.append(
                f"Missing tables detected: {', '.join(missing)}. " "Run: alembic upgrade head"
            )
        if not alembic_version:
            suggestions.append(
                "Alembic version table not found. " "Database may need fresh migration."
            )

        return {
            "existing_tables": list(existing),
            "missing_tables": list(missing),
            "alembic_version": alembic_version,
            "suggestions": suggestions,
        }
    finally:
        await conn.close()


async def verify_neo4j_constraints(
    neo4j_pool: Any,
) -> tuple[bool, list[str]]:
    """Verify that all required Neo4j constraints exist.

    Args:
        neo4j_pool: Neo4j connection pool.

    Returns:
        Tuple of (all_constraints_exist, list of missing constraint names).
    """
    try:
        # Get existing constraints
        result = await neo4j_pool.execute_query("SHOW CONSTRAINTS")
        existing_names = {record.get("name", "") for record in result}

        missing = []
        for constraint in REQUIRED_NEO4J_CONSTRAINTS:
            if constraint["name"] not in existing_names:
                missing.append(constraint["name"])

        all_exist = len(missing) == 0
        return all_exist, missing

    except Exception as e:
        log.warning("neo4j_constraint_check_failed", error=str(e))
        return False, [f"Failed to check constraints: {e}"]


async def initialize_neo4j(
    neo4j_pool: Any,
    create_constraints: bool = True,
) -> dict[str, Any]:
    """Initialize Neo4j with required constraints and indexes.

    This function ensures that all required Neo4j constraints and indexes
    are created for the application to function correctly.

    Args:
        neo4j_pool: Neo4j connection pool.
        create_constraints: Whether to create missing constraints.

    Returns:
        Dict with initialization status including:
        - constraints_verified: Whether all constraints exist
        - constraints_created: List of constraints that were created
        - errors: List of any errors encountered
    """
    result: dict[str, Any] = {
        "constraints_verified": False,
        "constraints_created": [],
        "errors": [],
    }

    try:
        # Check existing constraints
        all_exist, missing = await verify_neo4j_constraints(neo4j_pool)

        if all_exist:
            result["constraints_verified"] = True
            log.info("neo4j_constraints_verified")
            return result

        if not create_constraints:
            result["errors"].append(f"Missing constraints: {', '.join(missing)}")
            return result

        # Create missing constraints
        for constraint in REQUIRED_NEO4J_CONSTRAINTS:
            if constraint["name"] in missing:
                try:
                    await neo4j_pool.execute_query(constraint["query"])
                    result["constraints_created"].append(constraint["name"])
                    log.info(
                        "neo4j_constraint_created",
                        name=constraint["name"],
                        description=constraint["description"],
                    )
                except Exception as e:
                    error_msg = f"Failed to create constraint {constraint['name']}: {e}"
                    result["errors"].append(error_msg)
                    log.warning(
                        "neo4j_constraint_creation_failed",
                        name=constraint["name"],
                        error=str(e),
                    )

        # Verify all constraints now exist
        all_exist, _ = await verify_neo4j_constraints(neo4j_pool)
        result["constraints_verified"] = all_exist

    except Exception as e:
        error_msg = f"Neo4j initialization failed: {e}"
        result["errors"].append(error_msg)
        log.error("neo4j_initialization_failed", error=str(e))

    return result

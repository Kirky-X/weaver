# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""SQLAlchemy event listeners for performance monitoring.

IMPORTANT: These listeners should NOT be registered at module import time
using @event.listens_for decorators, as that interferes with SQLAlchemy's
asyncpg dialect version detection on PostgreSQL 16+. Instead, register
them dynamically via engine events in PostgresPool.startup().
"""

import time

from sqlalchemy import event
from sqlalchemy.engine import Connection

from core.observability import get_logger

log = get_logger(__name__)

# Slow query threshold in milliseconds (configurable via conn.info)
DEFAULT_SLOW_QUERY_THRESHOLD_MS = 100


# NOTE: Removed global @event.listens_for decorators to avoid
# interfering with asyncpg dialect initialization. These listeners
# are now registered dynamically in PostgresPool.startup().
# See: https://github.com/sqlalchemy/sqlalchemy/issues/13078


def before_cursor_execute(
    conn: Connection,
    cursor,
    statement: str,
    parameters,
    context,
    executemany: bool,
) -> None:
    """Record query start time.

    Args:
        conn: SQLAlchemy connection.
        cursor: DBAPI cursor.
        statement: SQL statement being executed.
        parameters: Statement parameters.
        context: Execution context.
        executemany: Whether this is an executemany operation.
    """
    conn.info.setdefault("query_start_time", []).append(time.time())
    log.debug("query_start", statement=statement[:100])


def after_cursor_execute(
    conn: Connection,
    cursor,
    statement: str,
    parameters,
    context,
    executemany: bool,
) -> None:
    """Log slow queries.

    Args:
        conn: SQLAlchemy connection.
        cursor: DBAPI cursor.
        statement: SQL statement that was executed.
        parameters: Statement parameters.
        context: Execution context.
        executemany: Whether this was an executemany operation.
    """
    if not conn.info.get("query_start_time"):
        return

    start_time = conn.info["query_start_time"].pop(-1)
    total_time = time.time() - start_time
    total_time_ms = total_time * 1000

    threshold_ms = conn.info.get("slow_query_threshold_ms", DEFAULT_SLOW_QUERY_THRESHOLD_MS)

    if total_time_ms > threshold_ms:
        log.warning(
            "slow_query_detected",
            duration_ms=round(total_time_ms, 2),
            threshold_ms=threshold_ms,
            statement=statement[:200],
            parameters=str(parameters)[:100] if parameters else None,
        )


def register_engine_events(engine) -> None:
    """Register event listeners on a SQLAlchemy engine.

    Args:
        engine: SQLAlchemy engine (sync or async engine's sync_engine).
    """
    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)

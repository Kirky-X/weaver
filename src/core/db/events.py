# Copyright (c) 2026 KirkyX. All Rights Reserved
"""SQLAlchemy event listeners for performance monitoring."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from sqlalchemy import event

from core.observability import get_logger

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

log = get_logger(__name__)

# Slow query threshold in milliseconds (configurable via conn.info)
DEFAULT_SLOW_QUERY_THRESHOLD_MS = 100


@event.listens_for(Connection, "before_cursor_execute")
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


@event.listens_for(Connection, "after_cursor_execute")
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

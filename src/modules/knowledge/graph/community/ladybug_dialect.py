# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB Cypher dialect adapter.

Centralizes Cypher query differences between Neo4j and LadybugDB:
- Relationship type access: Neo4j uses type(r), LadybugDB uses r.edge_type
- Relationship pattern: Neo4j uses [r], LadybugDB uses [r:RELATED_TO]
- Datetime function: Neo4j uses datetime(), LadybugDB requires Python-side timestamp
- Pruned property: Neo4j Entity nodes have pruned, LadybugDB does not
"""

from __future__ import annotations

from core.constants import DatabaseType


class LadybugDialect:
    """LadybugDB Cypher dialect adapter.

    Provides helper methods to generate database-type-specific Cypher fragments,
    reducing scattered if-else branches across community updater files.
    """

    @staticmethod
    def is_ladybug(database_type: str | None) -> bool:
        """Check if the database type is LadybugDB.

        Args:
            database_type: Database type string (e.g., "ladybug", "neo4j").

        Returns:
            True if database_type is LadybugDB.
        """
        return database_type == DatabaseType.LADYBUG.value

    @staticmethod
    def related_to_pattern(database_type: str | None) -> str:
        """Get relationship pattern for RELATED_TO edges.

        Neo4j: [r] (any relationship type)
        LadybugDB: [r:RELATED_TO] (must specify type explicitly)

        Args:
            database_type: Database type string.

        Returns:
            Cypher relationship pattern string.
        """
        if LadybugDialect.is_ladybug(database_type):
            return "[r:RELATED_TO]"
        return "[r]"

    @staticmethod
    def edge_type_filter(database_type: str | None, edge_type: str = "RELATED_TO") -> str:
        """Get edge type filter condition.

        Neo4j: type(r) = 'RELATED_TO'
        LadybugDB: r.edge_type = 'RELATED_TO' (or omit if using [r:RELATED_TO] pattern)

        Args:
            database_type: Database type string.
            edge_type: Edge type to filter (default: RELATED_TO).

        Returns:
            Cypher filter condition string, or empty string for LadybugDB
            (when using typed pattern, filter is redundant).
        """
        if LadybugDialect.is_ladybug(database_type):
            return ""  # Using [r:RELATED_TO] pattern, no need for type filter
        return f"type(r) = '{edge_type}'"

    @staticmethod
    def pruned_condition(database_type: str | None, var: str = "e") -> str:
        """Get pruned property filter condition for Entity nodes.

        Neo4j: (e.pruned IS NULL OR e.pruned = false)
        LadybugDB: "" (no pruned property in schema)

        Args:
            database_type: Database type string.
            var: Cypher variable name for the Entity node (default: "e").

        Returns:
            Cypher condition string, or empty string for LadybugDB.
        """
        if LadybugDialect.is_ladybug(database_type):
            return ""
        return f"({var}.pruned IS NULL OR {var}.pruned = false)"

    @staticmethod
    def now_expression(database_type: str | None) -> str:
        """Get current timestamp expression.

        Neo4j: datetime()
        LadybugDB: $now (Python-side timestamp passed as parameter)

        Args:
            database_type: Database type string.

        Returns:
            Cypher timestamp expression string.
        """
        if LadybugDialect.is_ladybug(database_type):
            return "$now"
        return "datetime()"

    @staticmethod
    def now_param(database_type: str | None) -> dict[str, int]:
        """Get now parameter for Cypher query.

        Neo4j: {} (no parameter needed, uses datetime())
        LadybugDB: {"now": int(datetime.now(UTC).timestamp())}
        Note: LadybugDB stores DateTime as INT64 (Unix timestamp).

        Args:
            database_type: Database type string.

        Returns:
            Dict with 'now' parameter for LadybugDB, empty dict for Neo4j.
        """
        if LadybugDialect.is_ladybug(database_type):
            from datetime import UTC, datetime

            return {"now": int(datetime.now(UTC).timestamp())}
        return {}

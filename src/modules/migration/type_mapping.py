# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Type mapping for database migrations.

Provides type conversion mappings between:
- PostgreSQL ↔ DuckDB (relational databases)
- Neo4j ↔ LadybugDB (graph databases)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .exceptions import TypeConversionError

# PostgreSQL to DuckDB type mapping
PG_TO_DUCKDB: dict[str, str] = {
    "uuid": "UUID",
    "varchar": "VARCHAR",
    "character varying": "VARCHAR",
    "text": "TEXT",
    "char": "CHAR",
    "character": "CHAR",
    "integer": "INTEGER",
    "int": "INTEGER",
    "int4": "INTEGER",
    "smallint": "SMALLINT",
    "int2": "SMALLINT",
    "bigint": "BIGINT",
    "int8": "BIGINT",
    "real": "FLOAT",
    "float4": "FLOAT",
    "double precision": "DOUBLE",
    "float8": "DOUBLE",
    "numeric": "DECIMAL",
    "decimal": "DECIMAL",
    "boolean": "BOOLEAN",
    "bool": "BOOLEAN",
    "date": "DATE",
    "time": "TIME",
    "timestamp": "TIMESTAMP",
    "timestamp without time zone": "TIMESTAMP",
    "timestamptz": "TIMESTAMP WITH TIME ZONE",
    "timestamp with time zone": "TIMESTAMP WITH TIME ZONE",
    "jsonb": "JSON",
    "json": "JSON",
    "bytea": "BLOB",
    "blob": "BLOB",
    "vector": "FLOAT[]",  # pgvector
}

# DuckDB to PostgreSQL type mapping (reverse of above)
DUCKDB_TO_PG: dict[str, str] = {
    "UUID": "uuid",
    "VARCHAR": "varchar",
    "TEXT": "text",
    "CHAR": "char",
    "INTEGER": "integer",
    "SMALLINT": "smallint",
    "BIGINT": "bigint",
    "FLOAT": "real",
    "DOUBLE": "double precision",
    "DECIMAL": "numeric",
    "BOOLEAN": "boolean",
    "DATE": "date",
    "TIME": "time",
    "TIMESTAMP": "timestamp",
    "TIMESTAMP WITH TIME ZONE": "timestamptz",
    "JSON": "jsonb",
    "BLOB": "bytea",
    "FLOAT[]": "vector",
}

# Neo4j to LadybugDB property type mapping
NEO4J_TO_LADYBUG: dict[str, str] = {
    "String": "STRING",
    "Integer": "INT64",
    "Long": "INT64",
    "Float": "DOUBLE",
    "Double": "DOUBLE",
    "Boolean": "BOOLEAN",
    "DateTime": "INT64",  # epoch milliseconds
    "LocalDateTime": "INT64",
    "Date": "INT64",
    "Point": "STRING",  # JSON serialized
    "List": "STRING",  # JSON serialized
    "Map": "STRING",  # JSON serialized
    "Node": "STRING",  # JSON serialized reference
    "Relationship": "STRING",  # JSON serialized reference
}

# LadybugDB to Neo4j property type mapping
LADYBUG_TO_NEO4J: dict[str, str] = {
    "STRING": "String",
    "INT64": "Long",
    "DOUBLE": "Double",
    "BOOLEAN": "Boolean",
}


def pg_type_to_duckdb(pg_type: str) -> str:
    """Convert PostgreSQL type to DuckDB type.

    Args:
        pg_type: PostgreSQL type name (case-insensitive).

    Returns:
        DuckDB type name.

    Raises:
        TypeConversionError: If type is not recognized.
    """
    normalized = pg_type.lower().strip()
    if normalized in PG_TO_DUCKDB:
        return PG_TO_DUCKDB[normalized]

    # Handle array types
    if normalized.endswith("[]"):
        base_type = normalized[:-2]
        if base_type in PG_TO_DUCKDB:
            return f"{PG_TO_DUCKDB[base_type]}[]"

    # Handle varchar(n), char(n), numeric(p,s)
    for prefix in ("varchar", "character varying", "char", "character", "numeric", "decimal"):
        if normalized.startswith(prefix):
            return PG_TO_DUCKDB[prefix]

    raise TypeConversionError(
        column="(type mapping)",
        value=pg_type,
        source_type="PostgreSQL",
        target_type="DuckDB",
    )


def duckdb_type_to_pg(duckdb_type: str) -> str:
    """Convert DuckDB type to PostgreSQL type.

    Args:
        duckdb_type: DuckDB type name.

    Returns:
        PostgreSQL type name.

    Raises:
        TypeConversionError: If type is not recognized.
    """
    normalized = duckdb_type.upper().strip()
    if normalized in DUCKDB_TO_PG:
        return DUCKDB_TO_PG[normalized]

    # Handle array types
    if normalized.endswith("[]"):
        base_type = normalized[:-2]
        if base_type in DUCKDB_TO_PG:
            return f"{DUCKDB_TO_PG[base_type]}[]"

    raise TypeConversionError(
        column="(type mapping)",
        value=duckdb_type,
        source_type="DuckDB",
        target_type="PostgreSQL",
    )


def neo4j_type_to_ladybug(neo4j_type: str) -> str:
    """Convert Neo4j property type to LadybugDB type.

    Args:
        neo4j_type: Neo4j type name (case-insensitive).

    Returns:
        LadybugDB type name.
    """
    normalized = neo4j_type.capitalize()
    return NEO4J_TO_LADYBUG.get(normalized, "STRING")


def ladybug_type_to_neo4j(ladybug_type: str) -> str:
    """Convert LadybugDB type to Neo4j property type.

    Args:
        ladybug_type: LadybugDB type name.

    Returns:
        Neo4j type name.
    """
    normalized = ladybug_type.upper()
    return LADYBUG_TO_NEO4J.get(normalized, "String")


def convert_value(
    value: Any,
    source_type: str,
    target_type: str,
    column: str = "(unknown)",
    table: str | None = None,
) -> Any:
    """Convert a value between database types.

    Args:
        value: Value to convert.
        source_type: Source database type.
        target_type: Target database type.
        column: Column name for error messages.
        table: Table name for error messages.

    Returns:
        Converted value.

    Raises:
        TypeConversionError: If conversion fails.
    """
    if value is None:
        return None

    source_lower = source_type.lower()
    target_lower = target_type.lower()

    try:
        # Timestamp conversions
        if "timestamp" in source_lower or "datetime" in source_lower:
            if isinstance(value, datetime):
                if "int64" in target_lower or "epoch" in target_lower:
                    # Convert to epoch milliseconds
                    return int(value.timestamp() * 1000)
                return value

        # Epoch to datetime
        if "int64" in source_lower or "epoch" in source_lower:
            if isinstance(value, (int, float)) and (
                "datetime" in target_lower or "timestamp" in target_lower
            ):
                return datetime.fromtimestamp(value / 1000, UTC)

        # JSON conversions
        if "json" in source_lower and target_lower in ("string", "varchar"):
            if isinstance(value, (dict, list)):
                return json.dumps(value)
            return str(value)

        if source_lower in ("string", "varchar") and "json" in target_lower:
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value

        # List/Array handling
        if source_lower in ("list", "array") or source_lower.endswith("[]"):
            if target_lower in ("string", "varchar"):
                if isinstance(value, list):
                    return json.dumps(value)
            return value

        # Decimal to float
        if isinstance(value, Decimal):
            if "float" in target_lower or "double" in target_lower:
                return float(value)
            if "int" in target_lower:
                return int(value)

        # Float/Int conversions
        if isinstance(value, float) and "int" in target_lower:
            return int(value)

        if isinstance(value, int) and ("float" in target_lower or "double" in target_lower):
            return float(value)

        # Boolean conversions
        if isinstance(value, bool):
            if "int" in target_lower:
                return 1 if value else 0
            if "string" in target_lower or "varchar" in target_lower:
                return str(value).lower()
            return value

        # String to boolean
        if isinstance(value, str):
            if "bool" in target_lower:
                return value.lower() in ("true", "1", "yes", "on")

        return value

    except Exception as exc:
        raise TypeConversionError(
            column=column,
            value=value,
            source_type=source_type,
            target_type=target_type,
            table=table,
        ) from exc


def get_compatible_type(source_type: str, target_db: str) -> str:
    """Get the most compatible type for a target database.

    Args:
        source_type: Source database type.
        target_db: Target database name ("postgres", "duckdb", "neo4j", "ladybug").

    Returns:
        Compatible type name for target database.
    """
    if target_db == "duckdb":
        return pg_type_to_duckdb(source_type)
    if target_db == "postgres":
        return duckdb_type_to_pg(source_type)
    if target_db == "ladybug":
        return neo4j_type_to_ladybug(source_type)
    if target_db == "neo4j":
        return ladybug_type_to_neo4j(source_type)

    return source_type

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Identifier validation for SQL and Cypher queries.

.. deprecated::
    This module is deprecated. Use ``core.db.safe_query`` instead,
    which is the canonical module for identifier validation.
    All functions and classes are re-exported from there for backward compatibility.
"""

from core.db.safe_query import (
    IdentifierValidator,
    InvalidIdentifierError,
    validate_edge_type as validate_cypher_edge_type,
    validate_neo4j_label as validate_cypher_label,
    validate_relation_types,
    validate_sql_identifier,
)

__all__ = [
    "IdentifierValidator",
    "InvalidIdentifierError",
    "validate_cypher_edge_type",
    "validate_cypher_label",
    "validate_relation_types",
    "validate_sql_identifier",
]

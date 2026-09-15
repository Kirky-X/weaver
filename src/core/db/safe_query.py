# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Safe query utilities for preventing SQL and Cypher injection.

This module provides validation functions and safe query building utilities
that enforce parameterized queries and input validation.

This is the canonical module for identifier validation.
"""

from __future__ import annotations

import re

# ── Validation Patterns ─────────────────────────────────────────────────────

# Valid SQL identifier: letters, digits, underscore, must start with letter or underscore
_SQL_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Valid Neo4j label: letters, digits, underscore, Chinese characters, must start with letter/underscore/Chinese
_NEO4J_LABEL_RE = re.compile(r"^[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*$")

# Valid edge type: uppercase letters, digits, underscore, Chinese characters.
# NOTE: Neo4j relationship types are case-sensitive, so a lower-case or
# mixed-case name (e.g. ``PartnersWith``) is legal in Neo4j but rejected here.
# The repo only seeds all-caps ``name_en`` values plus CJK names, so this
# constraint is safe today; relax the first-char class if that ever changes.
_EDGE_TYPE_RE = re.compile(r"^[A-Z_\u4e00-\u9fff][A-Z_\u4e00-\u9fff0-9]*$")

# Valid UUID string: 8-4-4-4-12 hex characters
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Valid Cypher variable-length hop pattern: '*1..3', '*..2', '*', '*0..N'
_HOP_PATTERN_RE = re.compile(r"^\*(?:\d+)?(?:\.\.\d*)?$")


# ── Validation Exceptions ───────────────────────────────────────────────────


class InvalidIdentifierError(ValueError):
    """Raised when an identifier fails validation."""

    def __init__(self, identifier: str, identifier_type: str) -> None:
        """Initialize with identifier and type."""
        super().__init__(f"Invalid {identifier_type}: '{identifier}'")
        self.identifier = identifier
        self.identifier_type = identifier_type


# ── Validation Functions ────────────────────────────────────────────────────


def validate_sql_identifier(identifier: str, name: str = "identifier") -> str:
    """Validate a SQL identifier (table name, column name).

    Enforces:
    - Minimum 2 characters (prevent single-char identifiers)
    - Maximum 63 characters (PostgreSQL identifier limit)
    - Only alphanumeric and underscore characters
    - Must start with letter or underscore

    Args:
        identifier: The identifier to validate.
        name: Human-readable name for error messages.

    Returns:
        The validated identifier (unchanged).

    Raises:
        InvalidIdentifierError: If the identifier is invalid.
    """
    if not identifier or len(identifier) < 2:
        raise InvalidIdentifierError(identifier, f"{name} (too short, min 2 chars)")

    if len(identifier) > 63:
        raise InvalidIdentifierError(identifier, f"{name} (too long, max 63 chars)")

    if not _SQL_IDENTIFIER_RE.match(identifier):
        raise InvalidIdentifierError(identifier, name)

    return identifier


def validate_neo4j_label(label: str) -> str:
    """Validate a Neo4j node label.

    Args:
        label: The label to validate.

    Returns:
        The validated label (unchanged).

    Raises:
        InvalidIdentifierError: If the label is invalid.
    """
    if not label:
        raise InvalidIdentifierError(label, "label (empty)")

    if not _NEO4J_LABEL_RE.match(label):
        raise InvalidIdentifierError(label, "Neo4j label")

    return label


def validate_edge_type(edge_type: str) -> str:
    """Validate an edge/relationship type for Neo4j.

    Args:
        edge_type: The edge type to validate.

    Returns:
        The validated edge type (unchanged).

    Raises:
        InvalidIdentifierError: If the edge type is invalid.
    """
    if not edge_type:
        raise InvalidIdentifierError(edge_type, "edge_type (empty)")

    if not _EDGE_TYPE_RE.match(edge_type):
        raise InvalidIdentifierError(edge_type, "edge type")

    return edge_type


def validate_hop_pattern(hop_pattern: str) -> str:
    """Validate a Cypher variable-length path hop pattern.

    Builder-layer defense in depth: hop patterns are interpolated into
    Cypher strings (they cannot be parameterized), so anything reaching
    a query builder must match the ``*`` / ``*N..M`` grammar.

    Args:
        hop_pattern: Pattern like ``*1..2``, ``*..3``, ``*``.

    Returns:
        The validated hop pattern (unchanged).

    Raises:
        InvalidIdentifierError: If the hop pattern is invalid.
    """
    if not hop_pattern:
        raise InvalidIdentifierError(hop_pattern, "hop_pattern (empty)")

    if not _HOP_PATTERN_RE.match(hop_pattern):
        raise InvalidIdentifierError(hop_pattern, "hop pattern")

    return hop_pattern


def validate_uuid(uuid_str: str, name: str = "uuid") -> str:
    """Validate a UUID string format.

    Args:
        uuid_str: The UUID string to validate.
        name: Human-readable name for error messages.

    Returns:
        The validated UUID string (unchanged).

    Raises:
        InvalidIdentifierError: If the UUID is invalid.
    """
    if not uuid_str:
        raise InvalidIdentifierError(uuid_str, f"{name} (empty)")

    # Simple UUID format check: 8-4-4-4-12 hex characters
    if not _UUID_RE.match(uuid_str):
        raise InvalidIdentifierError(uuid_str, name)

    return uuid_str


def validate_relation_types(relation_types: list[str]) -> list[str]:
    """Validate a list of relation types (edge types).

    Args:
        relation_types: List of edge types to validate.

    Returns:
        The validated list (unchanged).

    Raises:
        InvalidIdentifierError: If any edge type fails validation.
    """
    for rt in relation_types:
        validate_edge_type(rt)
    return relation_types

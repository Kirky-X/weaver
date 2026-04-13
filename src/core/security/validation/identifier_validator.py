# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Identifier validation for SQL and Cypher queries.

Provides whitelist-based validation for identifiers (table names, column names,
edge types, labels) to prevent SQL/Cypher injection attacks.
"""

import re
from dataclasses import dataclass

# SQL identifier pattern: alphanumeric + underscore, starting with letter/underscore
SQL_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Cypher identifier pattern: uppercase letters, underscore, Chinese characters, numbers
# Edge types like RELATED_TO, MENTIONS, etc.
CYPHER_EDGE_TYPE_PATTERN = re.compile(r"^[A-Z_\u4e00-\u9fff][A-Z_\u4e00-\u9fff0-9]*$")

# Cypher label pattern: alphanumeric, underscore, Chinese characters
CYPHER_LABEL_PATTERN = re.compile(r"^[a-zA-Z_\u4e00-\u9fff][a-zA-Z_\u4e00-\u9fff0-9]*$")


class InvalidIdentifierError(ValueError):
    """Raised when identifier fails validation."""

    def __init__(self, identifier: str, identifier_type: str, pattern: str) -> None:
        """Initialize error with context.

        Args:
            identifier: The invalid identifier value.
            identifier_type: Type of identifier (table, column, edge_type, label).
            pattern: The regex pattern that failed to match.
        """
        self.identifier = identifier
        self.identifier_type = identifier_type
        self.pattern = pattern
        super().__init__(
            f"Invalid {identifier_type} identifier: '{identifier}'. Must match pattern: {pattern}"
        )


def validate_sql_identifier(identifier: str, identifier_type: str = "SQL") -> str:
    """Validate SQL identifier (table name, column name).

    Args:
        identifier: The identifier to validate.
        identifier_type: Type description for error messages.

    Returns:
        The validated identifier (unchanged).

    Raises:
        InvalidIdentifierError: If identifier fails validation.
    """
    if not SQL_IDENTIFIER_PATTERN.match(identifier):
        raise InvalidIdentifierError(
            identifier=identifier,
            identifier_type=identifier_type,
            pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$",
        )
    return identifier


def validate_cypher_edge_type(edge_type: str) -> str:
    """Validate Cypher edge type (relationship type).

    Edge types must be uppercase with underscores and optional Chinese characters.
    Examples: RELATED_TO, MENTIONS, 合作关系

    Args:
        edge_type: The edge type to validate.

    Returns:
        The validated edge type (unchanged).

    Raises:
        InvalidIdentifierError: If edge type fails validation.
    """
    if not CYPHER_EDGE_TYPE_PATTERN.match(edge_type):
        raise InvalidIdentifierError(
            identifier=edge_type,
            identifier_type="edge_type",
            pattern=r"^[A-Z_\u4e00-\u9fff][A-Z_\u4e00-\u9fff0-9]*$",
        )
    return edge_type


def validate_cypher_label(label: str) -> str:
    """Validate Cypher label (node label).

    Labels must start with letter/underscore/Chinese and contain alphanumeric/underscore/Chinese.
    Examples: Entity, Article, 实体

    Args:
        label: The label to validate.

    Returns:
        The validated label (unchanged).

    Raises:
        InvalidIdentifierError: If label fails validation.
    """
    if not CYPHER_LABEL_PATTERN.match(label):
        raise InvalidIdentifierError(
            identifier=label,
            identifier_type="label",
            pattern=r"^[a-zA-Z_\u4e00-\u9fff][a-zA-Z_\u4e00-\u9fff0-9]*$",
        )
    return label


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
        validate_cypher_edge_type(rt)
    return relation_types


@dataclass
class IdentifierValidator:
    """Validator for database identifiers.

    Provides centralized validation for all identifier types.

    Example:
        validator = IdentifierValidator()
        table_name = validator.validate_table("users")
        edge_type = validator.validate_edge_type("RELATED_TO")
    """

    def validate_table(self, name: str) -> str:
        """Validate table name."""
        return validate_sql_identifier(name, "table")

    def validate_column(self, name: str) -> str:
        """Validate column name."""
        return validate_sql_identifier(name, "column")

    def validate_edge_type(self, edge_type: str) -> str:
        """Validate Cypher edge type."""
        return validate_cypher_edge_type(edge_type)

    def validate_label(self, label: str) -> str:
        """Validate Cypher label."""
        return validate_cypher_label(label)

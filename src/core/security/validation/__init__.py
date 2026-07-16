# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Security validation module.

Provides validation utilities for URLs, identifiers, and other security checks.
"""

from core.db.safe_query import (
    InvalidIdentifierError,
    validate_edge_type as validate_cypher_edge_type,
    validate_neo4j_label as validate_cypher_label,
    validate_relation_types,
    validate_sql_identifier,
)
from core.security.validation.ssrf import SSRFChecker, SSRFError
from core.security.validation.validator import URLValidator, URLValidatorConfig

__all__ = [
    # Identifier validation
    "InvalidIdentifierError",
    # SSRF validation
    "SSRFChecker",
    "SSRFError",
    # URL validation
    "URLValidator",
    "URLValidatorConfig",
    "validate_cypher_edge_type",
    "validate_cypher_label",
    "validate_relation_types",
    "validate_sql_identifier",
]

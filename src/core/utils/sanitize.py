# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Sensitive data sanitization utilities.

This module provides utilities for sanitizing sensitive data before logging.
It ensures that credentials, DSNs, and other sensitive information are
not exposed in log output.
"""

from __future__ import annotations

import re

# Patterns for sensitive data detection
SENSITIVE_PATTERNS = [
    # PostgreSQL DSN: postgresql://user:pass@host/db
    (r"(postgresql(?:\+[a-z]+)?://[^:]+:)([^@]+)(@.+)", r"\1***\3"),
    # Redis URL: redis://user:pass@host
    (r"(redis://[^:]+:)([^@]+)(@.+)", r"\1***\3"),
    # Neo4j URL: bolt://user:pass@host
    (r"(bolt://[^:]+:)([^@]+)(@.+)", r"\1***\3"),
    # API keys in URL params
    (r"([?&]api[_-]?key=)([^&]+)", r"\1***"),
    # Password in connection strings
    (r"(password[\"']?\s*[=:]\s*[\"']?)([^\"'\s,]+)", r"\1***"),
    # Generic secret/token patterns
    (r"(token[\"']?\s*[=:]\s*[\"']?)([^\"'\s,]+)", r"\1***"),
    (r"(secret[\"']?\s*[=:]\s*[\"']?)([^\"'\s,]+)", r"\1***"),
]


def sanitize_dsn(dsn: str) -> str:
    """Sanitize a database/connection string by hiding credentials.

    Args:
        dsn: Connection string that may contain credentials.

    Returns:
        Sanitized string with credentials replaced by ***.

    Example:
        >>> sanitize_dsn("postgresql://user:secret123@localhost/db")
        "postgresql://user:***@localhost/db"
    """
    if not dsn:
        return dsn

    result = dsn
    for pattern, replacement in SENSITIVE_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result

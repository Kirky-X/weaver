# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Sensitive data sanitization utilities.

This module provides utilities for sanitizing sensitive data before logging.
It ensures that credentials, DSNs, and other sensitive information are
not exposed in log output.
"""

from __future__ import annotations

import re

# Patterns for sensitive data detection.
# 预编译并在此处传入 IGNORECASE，避免日志热路径上的每次 re.sub 都走一遍
# 编译缓存查找。
SENSITIVE_PATTERNS = [
    # PostgreSQL DSN: postgresql://user:pass@host/db
    (re.compile(r"(postgresql(?:\+[a-z]+)?://[^:]+:)([^@]+)(@.+)", re.IGNORECASE), r"\1***\3"),
    # Redis URL: redis://user:pass@host
    (re.compile(r"(redis://[^:]+:)([^@]+)(@.+)", re.IGNORECASE), r"\1***\3"),
    # Neo4j URL: bolt://user:pass@host
    (re.compile(r"(bolt://[^:]+:)([^@]+)(@.+)", re.IGNORECASE), r"\1***\3"),
    # API keys in URL params
    (re.compile(r"([?&]api[_-]?key=)([^&]+)", re.IGNORECASE), r"\1***"),
    # Password in connection strings. Value excludes `*` (same idempotency
    # rationale as the token/secret patterns below)
    (re.compile(r"(password[\"']?\s*[=:]\s*[\"']?)([^\"'\s,*]+)", re.IGNORECASE), r"\1***"),
    # Generic secret/token patterns. The value excludes `*` so an already
    # redacted `***REDACTED***` value (e.g. from a second sanitizer pass)
    # is not rewritten again.
    (re.compile(r"(token[\"']?\s*[=:]\s*[\"']?)([^\"'\s,*]+)", re.IGNORECASE), r"\1***"),
    (re.compile(r"(secret[\"']?\s*[=:]\s*[\"']?)([^\"'\s,*]+)", re.IGNORECASE), r"\1***"),
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
        result = pattern.sub(replacement, result)

    return result

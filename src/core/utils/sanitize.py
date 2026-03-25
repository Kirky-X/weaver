# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Sensitive data sanitization utilities.

This module provides utilities for sanitizing sensitive data before logging.
It ensures that credentials, DSNs, and other sensitive information are
not exposed in log output.
"""

from __future__ import annotations

import re
from typing import Any

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


def sanitize_dict(data: dict[str, Any], sensitive_keys: set[str] | None = None) -> dict[str, Any]:
    """Sanitize a dictionary by masking sensitive values.

    Args:
        data: Dictionary to sanitize.
        sensitive_keys: Set of key names to consider sensitive.
            Defaults to common sensitive key names.

    Returns:
        New dictionary with sensitive values masked.
    """
    if sensitive_keys is None:
        sensitive_keys = {
            "password",
            "passwd",
            "pwd",
            "secret",
            "secret_key",
            "secretkey",
            "api_key",
            "apikey",
            "api-key",
            "token",
            "access_token",
            "refresh_token",
            "credential",
            "credentials",
            "private_key",
            "privatekey",
            "authorization",
            "auth",
        }

    result = {}
    for key, value in data.items():
        key_lower = key.lower().replace("-", "_")

        if key_lower in sensitive_keys:
            result[key] = "***"
        elif isinstance(value, str) and any(
            pattern in value.lower()
            for pattern in ["postgresql://", "redis://", "bolt://", "password="]
        ):
            result[key] = sanitize_dsn(value)
        elif isinstance(value, dict):
            result[key] = sanitize_dict(value, sensitive_keys)
        elif isinstance(value, list):
            result[key] = [
                sanitize_dict(item, sensitive_keys) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value

    return result


def sanitize_for_log(message: str) -> str:
    """Sanitize a log message string by masking sensitive patterns.

    Args:
        message: Log message that may contain sensitive data.

    Returns:
        Sanitized message with sensitive data masked.
    """
    if not message:
        return message

    result = message
    for pattern, replacement in SENSITIVE_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result

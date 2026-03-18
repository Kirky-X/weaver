"""loguru configuration for formatted logging."""

from __future__ import annotations

import re
import sys
from contextvars import ContextVar
from typing import Any

from loguru import logger
from opentelemetry import trace


_context_vars: ContextVar[dict[str, Any]] = ContextVar("context_vars", default={})


def get_trace_id() -> str:
    """Extract trace_id from OpenTelemetry context.

    Returns:
        The trace_id as a 32-character hex string, or "N/A" if no active span.
    """
    span = trace.get_current_span()
    span_context = span.get_span_context()

    if span_context and span_context.is_valid:
        # Format trace_id as 32-character hex string
        return format(span_context.trace_id, '032x')

    return "N/A"


# Patterns for sensitive data detection
SENSITIVE_PATTERNS = [
    # Password patterns
    (re.compile(r'(password|pwd|passwd)=([^\s,;]+)', re.IGNORECASE), r'\1=***REDACTED***'),
    (re.compile(r'(password|pwd|passwd)":"([^"]+)"', re.IGNORECASE), r'\1":"***REDACTED***"'),
    (re.compile(r'(password|pwd|passwd)\'([^\']+)\'', re.IGNORECASE), r'\1\'***REDACTED***\''),
    # API key patterns
    (re.compile(r'(api_key|apikey|api-key)=([^\s,;]+)', re.IGNORECASE), r'\1=***REDACTED***'),
    (re.compile(r'(api_key|apikey|api-key)":"([^"]+)"', re.IGNORECASE), r'\1":"***REDACTED***"'),
    (re.compile(r'(api_key|apikey|api-key)\'([^\']+)\'', re.IGNORECASE), r'\1\'***REDACTED***\''),
    # Connection string patterns
    (re.compile(r'(postgres|mysql|mongodb|redis)://([^:]+):([^@]+)@', re.IGNORECASE), r'\1://\2:***REDACTED***@'),
    # Bearer token patterns
    (re.compile(r'(bearer|token)\s+([^\s]+)', re.IGNORECASE), r'\1 ***REDACTED***'),
]


def redact_sensitive_data(message: str) -> str:
    """Redact sensitive information from log messages.

    Args:
        message: The log message to sanitize.

    Returns:
        Sanitized message with sensitive data replaced by ***REDACTED***.
    """
    sanitized = message
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def log_filter(record: Any) -> bool:
    """Filter and sanitize log records to remove sensitive data.

    Args:
        record: The loguru record to filter.

    Returns:
        Always True (allows the record), but modifies the message in-place.
    """
    # Add trace_id to the record's extra fields
    record['extra']['trace_id'] = get_trace_id()

    # Sanitize the log message
    if hasattr(record, 'message') and isinstance(record['message'], str):
        record['message'] = redact_sensitive_data(record['message'])

    # Sanitize any extra fields
    if hasattr(record, 'extra'):
        for key, value in record['extra'].items():
            if isinstance(value, str):
                record['extra'][key] = redact_sensitive_data(value)

    return True


def configure_logging(debug: bool = False) -> None:
    """Configure loguru with formatted output and context vars.

    Args:
        debug: If True, use a lower log level for development.
    """
    level = "DEBUG" if debug else "INFO"

    logger.remove()

    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <yellow>trace_id={extra[trace_id]}</yellow> - <level>{message}</level>",
        level=level,
        filter=log_filter,
    )


def get_logger(name: str | None = None) -> Any:
    """Get a loguru logger with context binding.

    Args:
        name: Optional logger name for context.

    Returns:
        A bound loguru logger instance.
    """
    bound_logger = logger.bind(**_context_vars.get())
    if name:
        bound_logger = bound_logger.bind(component=name)
    return bound_logger

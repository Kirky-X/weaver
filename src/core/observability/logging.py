# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""loguru configuration for formatted logging.

Features:
- Structured logging with trace_id integration
- Sensitive data redaction
- File output with rotation support
- Environment-based configuration

Note: SENSITIVE_PATTERNS are defined locally; redact_sensitive_data also
applies core.utils.sanitize's URL credential patterns (postgresql/redis
DSNs, `token:` forms, ?api_key=).
"""

from __future__ import annotations

import re
import sys
from contextvars import ContextVar
from typing import Any

from loguru import logger
from opentelemetry import trace

_context_vars: ContextVar[dict[str, Any]] = ContextVar("context_vars", default={})

# Default configuration (fallbacks, actual values come from ObservabilitySettings)
DEFAULT_LOG_FILE = ""
DEFAULT_LOG_ROTATION = "10 MB"
DEFAULT_LOG_RETENTION = "7 days"


def set_task_context(task_id: str, task_type: str = "scheduler") -> None:
    """Set context variables for background tasks (scheduler jobs, event handlers).

    This allows background tasks to have meaningful identifiers in logs
    instead of N/A for request_id.

    Args:
        task_id: Unique identifier for the task (e.g., job_id like "flush_retry_queue").
        task_type: Type of task (scheduler, event_handler, pipeline, etc).
    """
    current = _context_vars.get()
    _context_vars.set(
        {
            **current,
            "task_id": task_id,
            "task_type": task_type,
        }
    )


def clear_task_context() -> None:
    """Clear task context variables after background task completes."""
    current = _context_vars.get()
    _context_vars.set({k: v for k, v in current.items() if k not in ("task_id", "task_type")})


def get_trace_id() -> str:
    """Extract trace_id from OpenTelemetry context.

    Returns:
        The trace_id as a 32-character hex string, or "N/A" if no active span.
    """
    span = trace.get_current_span()
    span_context = span.get_span_context()

    if span_context and span_context.is_valid:
        # Format trace_id as 32-character hex string
        return format(span_context.trace_id, "032x")

    return "N/A"


# Patterns for sensitive data detection in logs
# Note: These patterns use ***REDACTED*** for clear log identification
SENSITIVE_PATTERNS = [
    # Password patterns
    (re.compile(r"(password|pwd|passwd)=([^\s,;]+)", re.IGNORECASE), r"\1=***REDACTED***"),
    (re.compile(r'(password|pwd|passwd)":"([^"]+)"', re.IGNORECASE), r'\1":"***REDACTED***"'),
    (re.compile(r"(password|pwd|passwd)'([^']+)'", re.IGNORECASE), r"\1'***REDACTED***'"),
    # API key patterns
    (re.compile(r"(api_key|apikey|api-key)=([^\s,;]+)", re.IGNORECASE), r"\1=***REDACTED***"),
    (re.compile(r'(api_key|apikey|api-key)":"([^"]+)"', re.IGNORECASE), r'\1":"***REDACTED***"'),
    (re.compile(r"(api_key|apikey|api-key)'([^']+)'", re.IGNORECASE), r"\1'***REDACTED***'"),
    # Connection string patterns
    (
        re.compile(r"(postgres|mysql|mongodb|redis|bolt)://([^:]+):([^@]+)@", re.IGNORECASE),
        r"\1://\2:***REDACTED***@",
    ),
    # Same schemes with an EMPTY user (`redis://:pw@host`) — the pattern
    # above requires at least one username character before the colon
    (
        re.compile(r"(\w[\w+.-]*://:)([^@]+)(@)", re.IGNORECASE),
        r"\1***REDACTED***\3",
    ),
    # Bearer/token patterns. The value must look like a credential
    # (>= 20 chars of token-alphabet characters) so prose such as
    # "token was refreshed" or "token count exceeded" is not redacted.
    (
        re.compile(
            r"((?:api[-_]?|access[-_]?|refresh[-_]?|auth[-_]?)?token|bearer)"
            r"[\s\"':=]+([A-Za-z0-9_\-+/=\.]{20,})",
            re.IGNORECASE,
        ),
        r"\1 ***REDACTED***",
    ),
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
    # Second pass: URL-credential forms (postgresql://user:pw@, token: x,
    # ?api_key=...) that the local patterns above don't cover. Deferred
    # import: core.utils.__init__ pulls article_enrichment which imports
    # this package — a module-level import here would be circular.
    from core.utils.sanitize import SENSITIVE_PATTERNS as URL_CREDENTIAL_PATTERNS

    for pattern, replacement in URL_CREDENTIAL_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


# Extra keys whose VALUE must be redacted wholesale. Key-level matching is
# needed because SENSITIVE_PATTERNS expect `key=value` inside one string,
# which never matches a bare extra value.
# Branch A (credentials): containment semantics — `db_password_value`,
# `Password1`, `secret_sauce` all match; over-redaction is the safe direction.
# Branch B (tokens): requires a word boundary before the token word and is
# end-anchored, so `id_token`/`access_token` match while `token_count`,
# `tokens_used` (counters/metadata, not credentials) do not.
_SENSITIVE_EXTRA_KEY_RE = re.compile(
    r"(?:password|pwd|passwd|api[_-]?key|secret|authorization)"
    r"|(?:^|[_-])(?:api[-_]?|access[-_]?|refresh[-_]?|auth[-_]?)?token$",
    re.IGNORECASE,
)


def log_filter(record: Any) -> bool:
    """Filter and sanitize log records to remove sensitive data.

    Also formats structured extra fields for output in the log message.

    Args:
        record: The loguru record to filter.

    Returns:
        Always True (allows the record), but modifies the message in-place.
    """
    # Add trace_id to the record's extra fields
    record["extra"]["trace_id"] = get_trace_id()

    # Get context vars for request_id or task_id fallback
    ctx = _context_vars.get()
    request_id = ctx.get("request_id")

    # Use request_id if available (HTTP requests), otherwise use task_id (background tasks)
    if request_id:
        record["extra"]["request_id"] = request_id
    else:
        task_id = ctx.get("task_id")
        task_type = ctx.get("task_type", "task")
        if task_id:
            # Format: task_type:task_id (e.g., "scheduler:flush_retry_queue")
            record["extra"]["request_id"] = f"{task_type}:{task_id}"
        else:
            record["extra"]["request_id"] = "N/A"

    # Sanitize the log message (loguru records are plain dicts — the old
    # hasattr(record, "message"/"extra") guards were always False, silently
    # disabling both redaction branches)
    if isinstance(record.get("message"), str):
        record["message"] = redact_sensitive_data(record["message"])

    # Sanitize any extra fields
    extra = record.get("extra")
    if extra:
        for key, value in extra.items():
            if _SENSITIVE_EXTRA_KEY_RE.search(key):
                # Credential-named key: redact the value whatever its type
                # (nested dict/list structures are not deep-scanned)
                extra[key] = "***REDACTED***"
            elif isinstance(value, str):
                extra[key] = redact_sensitive_data(value)

    # Format structured extra fields for output (excluding internal fields)
    _INTERNAL_FIELDS = {"request_id", "trace_id", "component", "_format_extra"}
    extra = record.get("extra", {})
    structured_fields = {k: v for k, v in extra.items() if k not in _INTERNAL_FIELDS}
    if structured_fields:
        # Format as key=value pairs
        formatted = " ".join(f"{k}={v}" for k, v in structured_fields.items())
        record["extra"]["_format_extra"] = formatted
    else:
        record["extra"]["_format_extra"] = ""

    return True


def configure_logging(
    debug: bool = False,
    log_file: str | None = None,
    log_rotation: str | None = None,
    log_retention: str | None = None,
    log_format: str = "text",
) -> None:
    """Configure loguru with formatted output and context vars.

    Args:
        debug: If True, use a lower log level for development.
        log_file: Path to log file. If None, uses LOG_FILE env var.
        log_rotation: Log rotation size/time. Default "10 MB".
        log_retention: Log retention period. Default "7 days".
        log_format: "text" (default, human-readable) or "json" (one JSON
            object per line for log collectors). Any other value raises
            ValueError before sinks are reconfigured.
    """
    if log_format not in ("text", "json"):
        raise ValueError(f"Unsupported log_format: {log_format!r} (expected 'text' or 'json')")

    level = "DEBUG" if debug else "INFO"
    serialize = log_format == "json"

    logger.remove()

    # Console output
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <yellow>req={extra[request_id]}</yellow> <yellow>trace={extra[trace_id]}</yellow> - <level>{message}</level> <dim>{extra[_format_extra]}</dim>",
        level=level,
        filter=log_filter,
        serialize=serialize,
    )

    # File output (if configured)
    file_path = log_file or DEFAULT_LOG_FILE
    if file_path:
        rotation = log_rotation or DEFAULT_LOG_ROTATION
        retention = log_retention or DEFAULT_LOG_RETENTION

        logger.add(
            file_path,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | req={extra[request_id]} trace={extra[trace_id]} - {message} {extra[_format_extra]}",
            level=level,
            filter=log_filter,
            rotation=rotation,
            retention=retention,
            compression="gz",  # Compress rotated logs
            enqueue=True,  # Thread-safe writes
            serialize=serialize,
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

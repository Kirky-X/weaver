# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Safe echoing of user-supplied identifiers into HTTPException detail strings.

Prevents reflected-XSS by HTML-escaping and truncating user input before it
is interpolated into error messages that may be rendered by frontends.
"""

from __future__ import annotations

from html import escape as html_escape

# Maximum length of user-supplied identifiers echoed in error details.
# Bounds log size and prevents overly long payloads from cluttering responses.
_MAX_DETAIL_ECHO_LEN = 64


def safe_echo(value: str) -> str:
    """Sanitize user input for safe inclusion in HTTPException detail strings.

    - HTML-escapes ``<``, ``>``, ``&``, ``"``, ``'`` so the value cannot break
      out of JSON strings or HTML context if a frontend renders the detail.
    - Truncates to ``_MAX_DETAIL_ECHO_LEN`` chars to bound log size.

    Args:
        value: Raw user-supplied string (e.g., source_id, task_id, host).

    Returns:
        Sanitized string safe to embed in error detail.
    """
    if not value:
        return ""
    truncated = value[:_MAX_DETAIL_ECHO_LEN]
    return html_escape(truncated, quote=True)


__all__ = ["safe_echo"]

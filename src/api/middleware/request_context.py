# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Request context middleware for logging and tracing."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from typing import Any

from core.observability import context_vars, get_logger

log = get_logger(__name__)

# X-Request-ID sanitization bounds: ASGI header values arrive as bytes and
# header injection rides on CR/LF, so anything outside printable ASCII is
# rejected and overlong values are truncated (log flooding guard).
_MAX_REQUEST_ID_LEN = 128
_PRINTABLE_ASCII_RE = re.compile(r"[ -~]+")

# Request-scoped context
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str | None) -> None:
    """Set the current request ID in context.

    Args:
        request_id: The request ID to set.

    """
    _request_id.set(request_id)


class RequestContextMiddleware:
    """Pure ASGI middleware to add request_id to all requests.

    Generates a unique request_id for each incoming HTTP request
    and adds it to both:
    - ContextVar for logging access
    - Response header for client correlation

    Attributes:
        HEADER_NAME: The HTTP header name for request ID.

    """

    HEADER_NAME = "X-Request-ID"

    def __init__(self, app: Any) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application to wrap.

        """
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Process the request and add request_id.

        Args:
            scope: The ASGI scope dictionary.
            receive: The ASGI receive callable.
            send: The ASGI send callable.

        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Get or generate request_id.
        # ASGI mandates lowercase header names; a mixed-case lookup would
        # never match, silently disabling client-provided request IDs.
        headers = dict(scope.get("headers", []))
        raw_request_id = headers.get(self.HEADER_NAME.encode().lower(), b"").decode(
            "ascii", errors="replace"
        )[:_MAX_REQUEST_ID_LEN]

        # Reject values containing CR/LF or non-printable characters
        # (header injection) and overlong values (log flooding) by falling
        # back to a server-generated UUID.
        if raw_request_id and _PRINTABLE_ASCII_RE.fullmatch(raw_request_id):
            request_id = raw_request_id
        else:
            if raw_request_id:
                log.warning(
                    "request_id_rejected",
                    reason="unprintable or invalid X-Request-ID header",
                )
            request_id = str(uuid.uuid4())

        # Set in context for logging access
        set_request_id(request_id)

        # Also set in the existing context_vars for loguru
        ctx = context_vars.get().copy()
        ctx["request_id"] = request_id
        context_vars.set(ctx)

        # Wrap send to add header to response
        header_added = False

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal header_added
            if message["type"] == "http.response.start" and not header_added:
                headers_list = list(message.get("headers", []))
                headers_list.append((self.HEADER_NAME.encode(), request_id.encode()))
                message["headers"] = headers_list
                header_added = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # Clear context
            set_request_id(None)
            ctx = context_vars.get().copy()
            ctx.pop("request_id", None)
            context_vars.set(ctx)

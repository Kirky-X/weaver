# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Request context middleware for logging and tracing."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

from core.observability.logging import get_logger

log = get_logger("request_context")

# Request-scoped context
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Get the current request ID from context.

    Returns:
        The request ID if set, None otherwise.

    """
    return _request_id.get()


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

        # Get or generate request_id
        headers = dict(scope.get("headers", []))
        request_id = headers.get(self.HEADER_NAME.encode(), b"").decode()

        if not request_id:
            request_id = str(uuid.uuid4())

        # Set in context for logging access
        set_request_id(request_id)

        # Also set in the existing context_vars for loguru
        from core.observability.logging import _context_vars

        ctx = _context_vars.get().copy()
        ctx["request_id"] = request_id
        _context_vars.set(ctx)

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
            ctx = _context_vars.get().copy()
            ctx.pop("request_id", None)
            _context_vars.set(ctx)

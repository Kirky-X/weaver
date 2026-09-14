# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Pure ASGI middleware components.

These middleware were previously defined in ``src/main.py`` and are extracted
here to reduce ``create_app()`` responsibility. They avoid BaseHTTPMiddleware
due to TestClient issues (see https://github.com/encode/starlette/issues/1931).
"""

from __future__ import annotations

from core.observability import get_logger

log = get_logger("main")

# Query parameter names whose values must never reach the logs
_SENSITIVE_QUERY_KEYS = frozenset({"key", "token", "password", "secret", "api_key", "access_token"})
_MAX_QUERY_LOG_LEN = 500


def redact_query(query: str, max_len: int = _MAX_QUERY_LOG_LEN) -> str:
    """Truncate a query string and mask values of sensitive parameter names."""
    if len(query) > max_len:
        query = query[:max_len]
    parts = []
    for pair in query.split("&"):
        name, sep, _value = pair.partition("=")
        if sep and name.lower() in _SENSITIVE_QUERY_KEYS:
            parts.append(f"{name}=***")
        else:
            parts.append(pair)
    return "&".join(parts)


class HTTPLoggingMiddleware:
    """Pure ASGI middleware to log all HTTP requests and responses.

    Response bodies are never logged unless ``log_response_body`` is
    enabled; when enabled the preview is DEBUG-level only so user data
    stays out of default production logs.
    """

    def __init__(self, app, log_response_body: bool = False):
        self.app = app
        self._log_response_body = log_response_body

    async def __call__(self, scope, receive, send):  # noqa: D102
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        query = scope.get("query_string", b"").decode("utf-8")
        headers = dict(scope.get("headers", []))

        # Extract client info
        client = scope.get("client", ("unknown", 0))
        client_host = client[0] if client else "unknown"

        # Log request
        api_key = headers.get(b"x-api-key", b"").decode("utf-8")
        if api_key:
            api_key_display = api_key[:8] + "..." if len(api_key) > 8 else api_key
        else:
            api_key_display = "none"

        log.info(
            "http_request",
            method=method,
            path=path,
            query=redact_query(query) if query else None,
            client=client_host,
            api_key=api_key_display,
        )

        # Capture response
        response_status = None
        response_headers = {}
        response_body_parts = []

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                nonlocal response_headers, response_status
                response_status = message.get("status", 0)
                response_headers = dict(message.get("headers", []))
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    response_body_parts.append(body)
            await send(message)

        await self.app(scope, receive, send_wrapper)

        # Log response
        response_body = b"".join(response_body_parts)
        content_type = response_headers.get(b"content-type", b"").decode("utf-8")

        if self._log_response_body:
            # Truncate body for logging (max 500 chars for JSON, 200 for others)
            if "application/json" in content_type:
                max_body_len = 500
            else:
                max_body_len = 200

            body_preview = response_body.decode("utf-8", errors="replace")[:max_body_len]
            if len(response_body) > max_body_len:
                body_preview += "..."

            log.debug(
                "http_response",
                status=response_status,
                path=path,
                method=method,
                content_type=content_type,
                body_preview=body_preview,
                body_size=len(response_body),
            )
        else:
            log.info(
                "http_response",
                status=response_status,
                path=path,
                method=method,
                content_type=content_type,
                body_size=len(response_body),
            )


class SecurityHeadersMiddleware:
    """Pure ASGI middleware to add security headers to all responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):  # noqa: D102
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"x-content-type-options"] = b"nosniff"
                headers[b"x-frame-options"] = b"DENY"
                headers[b"x-xss-protection"] = b"1; mode=block"
                headers[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                headers[b"content-security-policy"] = b"default-src 'none'; frame-ancestors 'none'"
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RequestSizeLimitMiddleware:
    """Pure ASGI middleware to limit request body size."""

    MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):  # noqa: D102
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        if method in ("POST", "PUT", "PATCH"):
            headers = dict(scope.get("headers", []))
            content_length = headers.get(b"content-length")
            if content_length and int(content_length) > self.MAX_REQUEST_SIZE:
                # Send 413 response
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"detail":"Request body too large"}',
                    }
                )
                return

        await self.app(scope, receive, send)

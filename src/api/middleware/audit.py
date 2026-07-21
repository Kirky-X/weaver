# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Audit logging middleware for admin and write endpoints.

Implements: Weaver-数据库设计文档 §12.3
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware

from core.observability import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from core.security import AuditLogService

log = get_logger(__name__)

# Write methods that trigger audit on write-only paths
_WRITE_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})

# Query parameter keys whose values must be redacted in audit logs to
# prevent credential / token leakage (CWE-532 fix).
_SENSITIVE_QUERY_PARAM_KEYS = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "key",
        "password",
        "passwd",
        "secret",
        "secret_key",
        "authorization",
        "auth",
        "code",  # OAuth authorization code
        "session",
        "session_id",
        "csrf_token",
        "x_api_key",
        "x-api-key",
    }
)

_REDACTED_PLACEHOLDER = "[REDACTED]"


def _redact_query_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of params with sensitive values redacted.

    Args:
        params: Original query_params dict from request.

    Returns:
        New dict where sensitive keys have their values replaced with
        ``[REDACTED]`` (CWE-532 fix).

    """
    redacted: dict[str, Any] = {}
    for k, v in params.items():
        if k.lower() in _SENSITIVE_QUERY_PARAM_KEYS:
            redacted[k] = _REDACTED_PLACEHOLDER
        else:
            redacted[k] = v
    return redacted


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Audit logging middleware for admin and write endpoints.

    Logs requests to admin endpoints (all methods) and write operations
    (POST/PUT/DELETE/PATCH) on configured paths to the audit_log table
    for security monitoring and compliance.

    Implements: Weaver-数据库设计文档 §12.3

    Args:
        app: ASGI application.
        audit_service: Optional service for persisting audit events to database.
        audited_paths: Path prefixes that are audited for ALL methods.
        write_only_paths: Path prefixes audited only for write methods.

    """

    def __init__(
        self,
        app,
        audit_service: AuditLogService | None = None,
        audited_paths: list[str] | None = None,
        write_only_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._audit_service = audit_service
        self._audited_paths = audited_paths or ["/api/v1/admin"]
        self._write_only_paths = write_only_paths or [
            "/api/v1/pipeline",
            "/api/v1/content",
            "/api/v1/graph",
        ]

    def _should_audit(self, path: str, method: str) -> bool:
        """Determine whether a request should be audited.

        Args:
            path: Request URL path.
            method: HTTP method.

        Returns:
            Whether the request should be audited.

        """
        # Admin paths: audit all methods
        for prefix in self._audited_paths:
            if path.startswith(prefix):
                return True

        # Write-only paths: audit only write methods
        if method in _WRITE_METHODS:
            for prefix in self._write_only_paths:
                if path.startswith(prefix):
                    return True

        return False

    async def dispatch(self, request: Request, call_next) -> Response:
        """Log audited endpoint access for security compliance.

        Args:
            request: HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            HTTP response.

        """
        # Only audit matching paths
        if not self._should_audit(request.url.path, request.method):
            return await call_next(request)

        # Process request
        start_time = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000

        # Log all admin requests (including failures for security audit)
        await self._log_audit_event(request, response, duration_ms)

        return response

    async def _log_audit_event(
        self,
        request: Request,
        response: Response,
        duration_ms: float,
    ) -> None:
        """Log audit event to audit_log table and structured logging.

        Args:
            request: HTTP request.
            response: HTTP response.
            duration_ms: Request duration in milliseconds.

        """
        try:
            # Extract client IP
            client_ip = request.client.host if request.client else "unknown"

            # Extract action from method and path
            action = f"{request.method}:{request.url.path}"

            # Extract target type and ID from path
            # Example: /api/v1/admin/articles/123 -> target_type="articles", target_id="123"
            path_parts = request.url.path.split("/")
            target_type: str | None = None
            target_id: str | None = None

            if len(path_parts) >= 5:
                target_type = path_parts[4]
            if len(path_parts) >= 6:
                target_id = path_parts[5]

            # Get API key from request state or headers
            key_id = getattr(request.state, "api_key_id", None)
            if not key_id:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    key_id = auth_header[7:15] + "..."
                else:
                    key_id = "anonymous"

            # Get user agent
            user_agent = request.headers.get("User-Agent")

            # Build detail object
            detail = {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                # CWE-532: redact sensitive query params before logging
                "query_params": _redact_query_params(dict(request.query_params)),
            }

            # Log to structured logging
            log.info(
                "audit_log",
                key_id=key_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail,
                client_ip=client_ip,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )

            # Write to audit_log table in database
            if self._audit_service:
                await self._audit_service.log_event(
                    key_id=key_id,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    detail=detail,
                    client_ip=client_ip,
                    user_agent=user_agent,
                )

        except Exception as e:
            # Audit logging should never break the request
            log.error(
                "audit_log_failed",
                error=str(e),
                exc_type=type(e).__name__,
                path=request.url.path,
            )

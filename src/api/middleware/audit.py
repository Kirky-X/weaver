# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Audit logging middleware for admin endpoints."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from core.observability import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

log = get_logger(__name__)

# Admin endpoint prefix to audit
ADMIN_PREFIX = "/api/v1/admin"


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Audit logging middleware for admin endpoints.
    
    Logs successful requests (2xx status codes) to admin endpoints
    to the audit_log table for security monitoring and compliance.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Log admin endpoint access for audit purposes.
        
        Args:
            request: HTTP request.
            call_next: Next middleware/handler in chain.
            
        Returns:
            HTTP response.
        """
        # Only audit admin endpoints
        if not request.url.path.startswith(ADMIN_PREFIX):
            return await call_next(request)

        # Process request
        start_time = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000

        # Only log successful requests (2xx status codes)
        if 200 <= response.status_code < 300:
            await self._log_audit_event(request, response, duration_ms)

        return response

    async def _log_audit_event(
        self,
        request: Request,
        response: Response,
        duration_ms: float,
    ) -> None:
        """Log audit event to audit_log table.
        
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
            target_type = "unknown"
            target_id = "unknown"
            
            if len(path_parts) >= 5:
                target_type = path_parts[4]  # "articles", "communities", etc.
            if len(path_parts) >= 6:
                target_id = path_parts[5]  # Article ID, community ID, etc.
            
            # Get API key from request state or headers
            key_id = getattr(request.state, "api_key_id", None)
            if not key_id:
                # Try to extract from Authorization header
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    key_id = auth_header[7:15] + "..."  # First 8 chars + ...
                else:
                    key_id = "anonymous"
            
            # Build detail object
            detail = {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "query_params": dict(request.query_params),
            }
            
            # Log audit event
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
            
            # TODO: In production, write to audit_log table in database
            # This requires database session from container
            # For now, we log to structured logging which can be collected by log aggregators
            
        except Exception as e:
            # Audit logging should never break the request
            log.error(
                "audit_log_failed",
                error=str(e),
                exc_type=type(e).__name__,
                path=request.url.path,
            )
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""HMAC signature verification middleware."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.observability import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

log = get_logger(__name__)

# Time window for signature validity (±30 seconds)
TIMESTAMP_TOLERANCE_SECONDS = 30

# Endpoints to skip signature verification
SKIP_PATHS = {"/health", "/metrics"}


class HMACSignatureMiddleware(BaseHTTPMiddleware):
    """HMAC signature verification middleware with optional dual-factor API key check.

    Validates request signatures using HMAC-SHA256 to ensure
    request authenticity and prevent replay attacks.

    When api_key is provided, both HMAC signature and X-API-Key must be present
    and valid (dual-factor verification). The HMAC signing key is independent
    from the API key.
    """

    def __init__(self, app, secret_key: str, api_key: str | None = None) -> None:
        """Initialize middleware with secret key and optional API key.

        Args:
            app: ASGI application.
            secret_key: Secret key for HMAC signature calculation.
            api_key: Optional API key for dual-factor verification.
                When provided, requests must include both valid HMAC
                signature and X-API-Key header.

        """
        super().__init__(app)
        self.secret_key = secret_key.encode("utf-8")
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next) -> Response:
        """Verify HMAC signature for incoming requests.

        Args:
            request: HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            HTTP response or 401 error if signature verification fails.

        """
        # Skip signature verification for certain endpoints
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        # Get signature headers
        signature = request.headers.get("X-Signature")
        timestamp_str = request.headers.get("X-Timestamp")

        # Check if both headers are present
        if not signature or not timestamp_str:
            log.warning(
                "missing_signature_headers",
                path=request.url.path,
                method=request.method,
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "missing_signature_headers"},
            )

        # Validate timestamp
        try:
            timestamp = float(timestamp_str)
        except ValueError:
            log.warning(
                "invalid_timestamp_format",
                path=request.url.path,
                timestamp=timestamp_str,
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "missing_signature_headers"},
            )

        # Check timestamp freshness (±30 seconds)
        current_time = time.time()
        if abs(current_time - timestamp) > TIMESTAMP_TOLERANCE_SECONDS:
            log.warning(
                "signature_expired",
                path=request.url.path,
                timestamp=timestamp,
                current_time=current_time,
                age_seconds=abs(current_time - timestamp),
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "signature_expired"},
            )

        # Read request body for signature calculation
        body = await request.body()
        body_str = body.decode("utf-8") if body else ""

        # Calculate expected signature
        message = f"{timestamp_str}:{request.method}:{request.url.path}:{body_str}"
        expected_signature = hmac.new(
            self.secret_key,
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Verify signature using constant-time comparison
        if not hmac.compare_digest(signature, expected_signature):
            log.warning(
                "signature_mismatch",
                path=request.url.path,
                method=request.method,
                provided_signature=signature[:16] + "...",
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "missing_signature_headers"},
            )

        # Signature is valid, proceed with request
        log.debug(
            "signature_verified",
            path=request.url.path,
            method=request.method,
        )

        # Dual-factor: verify API key if configured
        if self.api_key is not None:
            request_api_key = request.headers.get("X-API-Key")
            if not request_api_key:
                log.warning(
                    "missing_api_key",
                    path=request.url.path,
                    method=request.method,
                )
                return JSONResponse(
                    status_code=401,
                    content={"detail": "missing_api_key"},
                )

            if not hmac.compare_digest(request_api_key, self.api_key):
                log.warning(
                    "invalid_api_key",
                    path=request.url.path,
                    method=request.method,
                )
                return JSONResponse(
                    status_code=401,
                    content={"detail": "invalid_api_key"},
                )

        return await call_next(request)

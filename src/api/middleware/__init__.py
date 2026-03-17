"""API middleware module - Request processing middleware.

This module provides middleware components:
- auth: API key authentication
- rate_limit: Request rate limiting using slowapi

Example usage:
    from api.middleware.auth import verify_api_key
    from api.middleware.rate_limit import limiter
"""

from api.middleware.auth import verify_api_key, api_key_header
from api.middleware.rate_limit import limiter

__all__ = [
    "verify_api_key",
    "api_key_header",
    "limiter",
]

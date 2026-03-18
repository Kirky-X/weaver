# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API middleware module - Request processing middleware.

This module provides middleware components:
- auth: API key authentication
- rate_limit: Request rate limiting using slowapi

Example usage:
    from api.middleware.auth import verify_api_key
    from api.middleware.rate_limit import limiter
"""

from api.middleware.auth import api_key_header, verify_api_key
from api.middleware.rate_limit import limiter

__all__ = [
    "api_key_header",
    "limiter",
    "verify_api_key",
]

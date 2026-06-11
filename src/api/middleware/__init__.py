# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API middleware module - Request processing middleware.

This module provides middleware components:
- auth: API key authentication
- rate_limit: Request rate limiting using Redis-backed token bucket

Example usage:
    from api.middleware.auth import verify_api_key
    from api.middleware.rate_limit import TokenBucketRateLimiter, RateLimitMiddleware
"""

from api.middleware.auth import api_key_header, verify_api_key
from api.middleware.rate_limit import LocalTokenBucket, RateLimitMiddleware, TokenBucketRateLimiter

__all__ = [
    "LocalTokenBucket",
    "RateLimitMiddleware",
    "TokenBucketRateLimiter",
    "api_key_header",
    "verify_api_key",
]

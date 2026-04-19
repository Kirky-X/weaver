# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Rate limiting middleware using slowapi."""

from __future__ import annotations


from fastapi import Request, Security
from fastapi.security import APIKeyHeader
from slowapi import Limiter
from slowapi.util import get_remote_address

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_client_key(request: Request, key: str | None = Security(api_key_header)) -> str:
    """Generate composite rate limit key from IP address and API key.

    Uses both client IP and API key to prevent distributed attacks.
    If no API key is provided, falls back to IP-only key.

    Args:
        request: The FastAPI request object.
        key: Optional API key from the request header.

    Returns:
        Composite key string in format 'ip:api_key' or just 'ip' if no key.

    """
    client_ip = get_remote_address(request)
    if key:
        return f"{client_ip}:{key}"
    return client_ip


limiter = Limiter(key_func=get_client_key)

"""API authentication middleware."""

from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    key: str | None = Security(api_key_header),
) -> str:
    """Verify the API key from the request header.

    Args:
        key: API key from the request header.

    Returns:
        The validated API key.

    Raises:
        HTTPException: If the API key is missing or invalid.
    """
    from container import get_settings
    settings = get_settings()

    if key is None:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-API-Key header.",
        )

    if key != settings.api.api_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API Key",
        )

    return key

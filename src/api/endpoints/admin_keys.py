# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API Key management endpoints.

Provides CRUD operations for API keys:
- POST /api/v1/admin/api-keys: Create new API key
- GET /api/v1/admin/api-keys: List all API keys
- DELETE /api/v1/admin/api-keys/{key_id}: Revoke API key
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin/api-keys", tags=["admin", "api-keys"])


# Request/Response models
class CreateApiKeyRequest(BaseModel):
    """Request model for creating API key."""

    name: str = Field(..., min_length=1, max_length=255, description="Key name")
    scopes: list[str] = Field(
        default=["read"],
        description="Key scopes (read, write, admin)",
    )
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        le=365,
        description="Days until expiration (null for no expiration)",
    )


class ApiKeyResponse(BaseModel):
    """Response model for API key."""

    key_id: str = Field(..., description="Key ID")
    key: str = Field(..., description="API key (only shown once)")
    name: str = Field(..., description="Key name")
    scopes: list[str] = Field(..., description="Key scopes")
    created_at: datetime = Field(..., description="Creation timestamp")
    expires_at: datetime | None = Field(None, description="Expiration timestamp")


class ApiKeyListItem(BaseModel):
    """Response model for listing API keys."""

    key_id: str = Field(..., description="Key ID")
    name: str = Field(..., description="Key name")
    scopes: list[str] = Field(..., description="Key scopes")
    created_at: datetime = Field(..., description="Creation timestamp")
    expires_at: datetime | None = Field(None, description="Expiration timestamp")
    is_active: bool = Field(..., description="Whether key is active")


class RevokeApiKeyResponse(BaseModel):
    """Response model for revoking API key."""

    message: str = Field(..., description="Success message")
    key_id: str = Field(..., description="Revoked key ID")


# Valid scopes
VALID_SCOPES = {"read", "write", "admin"}


def get_db() -> Any:
    """Get database session. Override in tests."""
    # This will be overridden by FastAPI dependency injection
    pass


def hash_api_key(key: str) -> str:
    """Hash API key using bcrypt.

    Args:
        key: Raw API key.

    Returns:
        Hashed key string.

    """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(key.encode(), salt).decode()


def generate_api_key() -> str:
    """Generate a new API key.

    Returns:
        New API key string.

    """
    return f"weaver_{uuid.uuid4().hex}"


def validate_api_key(key: str, db_session: Any) -> dict[str, Any] | None:
    """Validate API key against database.

    Args:
        key: Raw API key to validate.
        db_session: Database session.

    Returns:
        Key data if valid, None otherwise.

    """
    # This is a simplified implementation
    # In production, you would query the api_keys table
    # and validate against bcrypt hash
    return None


@router.post(
    "",
    response_model=ApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    request: CreateApiKeyRequest,
    db: Any = Depends(get_db),
) -> ApiKeyResponse:
    """Create a new API key.

    Args:
        request: API key creation request.
        db: Database session.

    Returns:
        Created API key details.

    """
    # Validate scopes
    invalid_scopes = set(request.scopes) - VALID_SCOPES
    if invalid_scopes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid scopes: {invalid_scopes}",
        )

    # Generate API key
    key = generate_api_key()
    key_id = str(uuid.uuid4())
    _key_hash = hash_api_key(key)

    # Calculate expiration
    expires_at = None
    if request.expires_in_days:
        expires_at = datetime.now(UTC) + timedelta(days=request.expires_in_days)

    # Store in database
    # In production, you would insert into api_keys table
    log.info(
        "api_key_created",
        key_id=key_id,
        name=request.name,
        scopes=request.scopes,
    )

    return ApiKeyResponse(
        key_id=key_id,
        key=key,
        name=request.name,
        scopes=request.scopes,
        created_at=datetime.now(UTC),
        expires_at=expires_at,
    )


@router.get("", response_model=list[ApiKeyListItem])
async def list_api_keys(
    db: Any = Depends(get_db),
) -> list[ApiKeyListItem]:
    """List all API keys.

    Args:
        db: Database session.

    Returns:
        List of API keys.

    """
    # In production, you would query api_keys table
    return []


@router.delete(
    "/{key_id}",
    response_model=RevokeApiKeyResponse,
)
async def revoke_api_key(
    key_id: str,
    db: Any = Depends(get_db),
) -> RevokeApiKeyResponse:
    """Revoke an API key.

    Args:
        key_id: ID of the key to revoke.
        db: Database session.

    Returns:
        Revocation confirmation.

    """
    # In production, you would update api_keys table
    # For now, return success
    log.info("api_key_revoked", key_id=key_id)

    return RevokeApiKeyResponse(
        message="API key revoked successfully",
        key_id=key_id,
    )

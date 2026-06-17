# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Admin endpoints for API key management.

Endpoints:
- POST /api-keys
- GET /api-keys
- DELETE /api-keys/{key_id}
- POST /api-keys/{key_id}/rotate
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response

router = APIRouter(prefix="/admin", tags=["admin"])


# ── API Key Management ───────────────────────────────────────────


class CreateApiKeyRequest(BaseModel):
    """Request model for creating a new API key."""

    scopes: list[str] = Field(default=["search:read"], description="Key scopes")
    rate_limit_per_min: int = Field(default=100, ge=10, le=10000, description="Rate limit")
    expires_in_days: int = Field(default=90, ge=1, le=365, description="Key validity in days")
    created_by: str | None = Field(default=None, description="Identifier for key owner")


class CreateApiKeyResponse(BaseModel):
    """Response model for key creation (key_value shown only once)."""

    key_id: str
    key_value: str
    scopes: list[str]
    rate_limit_per_min: int
    expires_at: str


class ApiKeyItem(BaseModel):
    """API key item in list response (without key_value)."""

    key_id: str
    scopes: list[str]
    rate_limit_per_min: int
    expires_at: str | None
    is_revoked: bool
    last_used_at: str | None
    created_by: str | None
    created_at: str | None


@router.post("/api-keys", response_model=APIResponse[CreateApiKeyResponse])
async def create_api_key(
    request: Request,
    body: CreateApiKeyRequest,
    _: str = Depends(verify_admin_api_key),
) -> APIResponse[CreateApiKeyResponse]:
    """Create a new API key.

    Requires admin privileges. Returns the key_value only once.
    """
    from container import get_container
    from core.security import ApiKeyManager

    container = get_container()
    pool = container.relational_pool()
    manager = ApiKeyManager(pool)

    result = await manager.create_key(
        scopes=body.scopes,
        rate_limit_per_min=body.rate_limit_per_min,
        expires_in_days=body.expires_in_days,
        created_by=body.created_by,
    )

    return success_response(
        CreateApiKeyResponse(
            key_id=result["key_id"],
            key_value=result["key_value"],
            scopes=result["scopes"],
            rate_limit_per_min=result["rate_limit_per_min"],
            expires_at=result["expires_at"],
        )
    )


@router.get("/api-keys", response_model=APIResponse[list[ApiKeyItem]])
async def list_api_keys(
    request: Request,
    include_revoked: bool = Query(False, description="Include revoked keys"),
    _: str = Depends(verify_admin_api_key),
) -> APIResponse[list[ApiKeyItem]]:
    """List all API keys (without key_value)."""
    from container import get_container
    from core.security import ApiKeyManager

    container = get_container()
    pool = container.relational_pool()
    manager = ApiKeyManager(pool)

    keys = await manager.list_keys(include_revoked=include_revoked)
    items = []
    for k in keys:
        items.append(
            ApiKeyItem(
                key_id=k.get("key_id", ""),
                scopes=k.get("scopes", ["search:read"]),
                rate_limit_per_min=k.get("rate_limit_per_min", 100),
                expires_at=str(k.get("expires_at")) if k.get("expires_at") else None,
                is_revoked=k.get("is_revoked", False),
                last_used_at=str(k.get("last_used_at")) if k.get("last_used_at") else None,
                created_by=k.get("created_by"),
                created_at=str(k.get("created_at")) if k.get("created_at") else None,
            )
        )

    return success_response(items)


@router.delete("/api-keys/{key_id}", response_model=APIResponse[dict])
async def revoke_api_key(
    request: Request,
    key_id: str,
    _: str = Depends(verify_admin_api_key),
) -> APIResponse[dict]:
    """Revoke an API key by key_id."""
    from container import get_container
    from core.security import ApiKeyManager

    container = get_container()
    pool = container.relational_pool()
    manager = ApiKeyManager(pool)

    revoked = await manager.revoke_key(key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")

    return success_response({"key_id": key_id, "revoked": True})


class RotateKeyResponse(BaseModel):
    """Response model for key rotation."""

    old_key_id: str
    new_key_id: str
    new_key_value: str
    scopes: list[str]
    rate_limit_per_min: int
    expires_at: str


@router.post("/api-keys/{key_id}/rotate", response_model=APIResponse[RotateKeyResponse])
async def rotate_api_key(
    request: Request,
    key_id: str,
    _: str = Depends(verify_admin_api_key),
) -> APIResponse[RotateKeyResponse]:
    """Manually rotate an API key, creating a replacement.

    The old key remains valid during a 24-hour grace period.
    The new key inherits the same scopes and rate limit.
    """
    from container import get_container
    from core.security import ApiKeyManager

    container = get_container()
    pool = container.relational_pool()
    manager = ApiKeyManager(pool)

    result = await manager.rotate_key(key_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")

    return success_response(
        RotateKeyResponse(
            old_key_id=key_id,
            new_key_id=result["key_id"],
            new_key_value=result["key_value"],
            scopes=result["scopes"],
            rate_limit_per_min=result["rate_limit_per_min"],
            expires_at=result["expires_at"],
        )
    )

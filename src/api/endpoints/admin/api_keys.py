# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Admin endpoints for API key management.

Endpoints:
- POST /api-keys
- GET /api-keys
- DELETE /api-keys/{key_id}
- POST /api-keys/{key_id}/rotate
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response
from core.security import AuditLogService, KeyOpResult, KeyOpStatus

router = APIRouter(prefix="/admin", tags=["admin"])


def _raise_for_key_op_status(result: KeyOpResult, key_id: str) -> None:
    """Raise HTTPException for non-OK KeyOpResult.

    Centralizes the KeyOpStatus → HTTP status code mapping to avoid
    duplication between revoke and rotate endpoints (LOW-002).
    """
    status_map = {
        KeyOpStatus.NOT_FOUND: (404, f"API key '{key_id}' not found"),
        KeyOpStatus.FORBIDDEN: (
            403,
            "Not authorized to manage this key. Only the key owner or a super-admin can operate.",
        ),
        KeyOpStatus.ALREADY_REVOKED: (409, f"API key '{key_id}' already revoked"),
        KeyOpStatus.ALREADY_ROTATED: (409, f"API key '{key_id}' already rotated"),
    }
    if result.status in status_map:
        code, detail = status_map[result.status]
        raise HTTPException(status_code=code, detail=detail)


# ── API Key Management ───────────────────────────────────────────

# Characters blocked in created_by to prevent stored XSS
_CREATED_BY_DANGEROUS_CHARS = frozenset({"<", ">", '"', "'", "&", ";", "(", ")"})


class CreateApiKeyRequest(BaseModel):
    """Request model for creating a new API key."""

    scopes: list[str] = Field(default=["search:read"], description="Key scopes")
    rate_limit_per_min: int = Field(default=100, ge=10, le=10000, description="Rate limit")
    expires_in_days: int = Field(default=90, ge=1, le=365, description="Key validity in days")
    created_by: str | None = Field(
        default=None, max_length=100, description="Identifier for key owner"
    )

    @field_validator("created_by")
    @classmethod
    def validate_created_by(cls, v: str | None) -> str | None:
        """Validate created_by to prevent stored XSS attacks."""
        if v is None:
            return v
        # Block dangerous characters that enable XSS/SQL injection
        found = _CREATED_BY_DANGEROUS_CHARS.intersection(v)
        if found:
            raise ValueError(f"created_by contains forbidden characters: {sorted(found)}")
        return v


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
    admin_id: str = Depends(verify_admin_api_key),
) -> APIResponse[dict]:
    """Revoke an API key by key_id.

    Ownership check (vuln-0009 fix): only the key's creator or a super-admin
    (``env-admin``) can revoke a key. All attempts — success or failure — are
    written to the audit log for security monitoring.
    """
    from container import get_container
    from core.security import ApiKeyManager

    container = get_container()
    pool = container.relational_pool()
    manager = ApiKeyManager(pool)

    result = await manager.revoke_key(key_id, actor=admin_id)

    # Audit log: record every attempt regardless of outcome so security
    # monitoring can detect probing patterns (vuln-0009).
    audit = AuditLogService(pool)
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    await audit.log_event(
        key_id=admin_id,
        action="api_key.revoke",
        target_type="api_key",
        target_id=key_id,
        detail={"status": result.status.value},
        client_ip=client_ip,
        user_agent=user_agent,
    )

    _raise_for_key_op_status(result, key_id)

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
    admin_id: str = Depends(verify_admin_api_key),
) -> APIResponse[RotateKeyResponse]:
    """Manually rotate an API key, creating a replacement.

    The old key remains valid during a 24-hour grace period.
    The new key inherits the same scopes and rate limit.

    Ownership check (vuln-0009 fix): only the key's creator or a super-admin
    (``env-admin``) can rotate a key. All attempts — success or failure — are
    written to the audit log for security monitoring.
    """
    from container import get_container
    from core.security import ApiKeyManager

    container = get_container()
    pool = container.relational_pool()
    manager = ApiKeyManager(pool)

    result = await manager.rotate_key(key_id, actor=admin_id)

    # Audit log: record every attempt regardless of outcome (vuln-0009).
    audit = AuditLogService(pool)
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    await audit.log_event(
        key_id=admin_id,
        action="api_key.rotate",
        target_type="api_key",
        target_id=key_id,
        detail={"status": result.status.value},
        client_ip=client_ip,
        user_agent=user_agent,
    )

    _raise_for_key_op_status(result, key_id)

    data = result.data or {}
    return success_response(
        RotateKeyResponse(
            old_key_id=key_id,
            new_key_id=data["key_id"],
            new_key_value=data["key_value"],
            scopes=data["scopes"],
            rate_limit_per_min=data["rate_limit_per_min"],
            expires_at=data["expires_at"],
        )
    )

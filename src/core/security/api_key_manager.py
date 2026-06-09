"""API Key management service.

Provides:
- Multi-key support with scopes and expiry
- bcrypt-hashed key storage
- Key creation, validation, and revocation
- Rate limit configuration per key
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from core.observability import get_logger

log = get_logger(__name__)


class ApiKeyManager:
    """API Key lifecycle management."""

    def __init__(self, pool):
        self._pool = pool

    async def create_key(
        self,
        scopes: list[str] | None = None,
        rate_limit_per_min: int = 100,
        expires_in_days: int = 90,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """Create a new API key.

        Args:
            scopes: Permission scopes (default: ["search:read"]).
            rate_limit_per_min: Max requests per minute.
            expires_in_days: Key validity period.
            created_by: Who created this key.

        Returns:
            Dict with key_id, key_value (show once), scopes, expires_at.
        """
        scopes = scopes or ["search:read"]
        key_value = secrets.token_urlsafe(32)
        key_id = f"key_{secrets.token_hex(8)}"
        expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)

        # Store bcrypt hash — never store raw key
        import hashlib

        key_hash = hashlib.sha256(key_value.encode()).hexdigest()

        await self._pool.execute(
            """
            INSERT INTO api_keys (key_id, key_hash, scopes, rate_limit_per_min, expires_at, created_by)
            VALUES ($1, $2, $3::jsonb, $4, $5, $6)
        """,
            key_id,
            key_hash,
            json.dumps(scopes),
            rate_limit_per_min,
            expires_at,
            created_by,
        )

        log.info("api_key_created", key_id=key_id, scopes=scopes, expires_at=expires_at.isoformat())

        return {
            "key_id": key_id,
            "key_value": key_value,  # 仅创建时返回一次
            "scopes": scopes,
            "rate_limit_per_min": rate_limit_per_min,
            "expires_at": expires_at.isoformat(),
        }

    async def validate_key(self, key_value: str) -> dict[str, Any] | None:
        """Validate an API key and return its info.

        Args:
            key_value: The raw API key to validate.

        Returns:
            Key info dict if valid, None if invalid/expired/revoked.
        """
        import hashlib

        key_hash = hashlib.sha256(key_value.encode()).hexdigest()

        row = await self._pool.fetchrow(
            """
            SELECT key_id, scopes, rate_limit_per_min, expires_at, is_revoked
            FROM api_keys
            WHERE key_hash = $1
        """,
            key_hash,
        )

        if not row:
            return None

        if row["is_revoked"]:
            log.warning("api_key_revoked_used", key_id=row["key_id"])
            return None

        if row["expires_at"] < datetime.now(UTC):
            log.warning("api_key_expired", key_id=row["key_id"])
            return None

        # Update last_used_at
        await self._pool.execute(
            "UPDATE api_keys SET last_used_at = NOW() WHERE key_id = $1",
            row["key_id"],
        )

        return {
            "key_id": row["key_id"],
            "scopes": row["scopes"],
            "rate_limit_per_min": row["rate_limit_per_min"],
            "expires_at": row["expires_at"].isoformat(),
        }

    async def revoke_key(self, key_id: str) -> bool:
        """Revoke an API key.

        Args:
            key_id: The key ID to revoke.

        Returns:
            True if revoked, False if not found.
        """
        result = await self._pool.execute(
            """
            UPDATE api_keys SET is_revoked = true WHERE key_id = $1
        """,
            key_id,
        )
        if result:
            log.info("api_key_revoked", key_id=key_id)
            return True
        return False

    async def list_keys(
        self,
        include_revoked: bool = False,
    ) -> list[dict[str, Any]]:
        """List all API keys (without key_value).

        Args:
            include_revoked: Whether to include revoked keys.

        Returns:
            List of key info dicts.
        """
        if include_revoked:
            rows = await self._pool.fetch("""
                SELECT key_id, scopes, rate_limit_per_min, expires_at, is_revoked,
                       last_used_at, created_by, created_at
                FROM api_keys ORDER BY created_at DESC
            """)
        else:
            rows = await self._pool.fetch("""
                SELECT key_id, scopes, rate_limit_per_min, expires_at, is_revoked,
                       last_used_at, created_by, created_at
                FROM api_keys WHERE is_revoked = false ORDER BY created_at DESC
            """)

        return [dict(r) for r in rows]

    async def get_rate_limit(self, key_id: str) -> int:
        """Get the rate limit for a specific key.

        Args:
            key_id: The key ID.

        Returns:
            Max requests per minute.
        """
        row = await self._pool.fetchrow(
            "SELECT rate_limit_per_min FROM api_keys WHERE key_id = $1",
            key_id,
        )
        return row["rate_limit_per_min"] if row else 100

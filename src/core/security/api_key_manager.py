# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API Key management service.

Provides:
- Multi-key support with scopes and expiry
- bcrypt-hashed key storage
- Key creation, validation, and revocation
- Rate limit configuration per key

Implements: Weaver-数据库设计文档 §1.6.3
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from sqlalchemy import select, update

from core.db.models import ApiKey
from core.observability import get_logger
from core.protocols import RelationalPool

log = get_logger(__name__)


class ApiKeyManager:
    """API Key lifecycle management with bcrypt hashing and ORM.

    Implements: Weaver-数据库设计文档 §1.6.3
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    @staticmethod
    def _hash_key(key_value: str) -> str:
        """Hash API key using bcrypt.

        Args:
            key_value: Raw API key string.

        Returns:
            bcrypt hash string (60 chars, starts with $2b$).
        """
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(key_value.encode(), salt).decode()

    @staticmethod
    def _verify_key(key_value: str, key_hash: str) -> bool:
        """Verify API key against bcrypt hash.

        Args:
            key_value: Raw API key string.
            key_hash: Stored bcrypt hash.

        Returns:
            True if key matches hash.
        """
        return bcrypt.checkpw(key_value.encode(), key_hash.encode())

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
        key_value = f"weaver_{uuid.uuid4().hex}"
        key_id = f"key_{secrets.token_hex(8)}"
        expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)

        # Store bcrypt hash — never store raw key
        key_hash = self._hash_key(key_value)

        api_key = ApiKey(
            key_id=key_id,
            key_hash=key_hash,
            scopes=scopes,
            rate_limit_per_min=rate_limit_per_min,
            expires_at=expires_at,
            created_by=created_by,
        )

        async with self._pool.session() as session:
            session.add(api_key)
            await session.commit()

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

        Uses bcrypt comparison to verify the key against stored hashes.

        Args:
            key_value: The raw API key to validate.

        Returns:
            Key info dict if valid, None if invalid/expired/revoked.
        """
        async with self._pool.session() as session:
            # Fetch all non-revoked, non-expired keys to compare
            result = await session.execute(
                select(ApiKey).where(ApiKey.is_revoked == False)  # noqa: E712
            )
            candidates = result.scalars().all()

            matched_key: ApiKey | None = None
            for candidate in candidates:
                if self._verify_key(key_value, candidate.key_hash):
                    matched_key = candidate
                    break

            if not matched_key:
                return None

            if matched_key.expires_at < datetime.now(UTC):
                log.warning("api_key_expired", key_id=matched_key.key_id)
                return None

            # Update last_used_at
            await session.execute(
                update(ApiKey)
                .where(ApiKey.key_id == matched_key.key_id)
                .values(last_used_at=datetime.now(UTC))
            )
            await session.commit()

            return {
                "key_id": matched_key.key_id,
                "scopes": matched_key.scopes,
                "rate_limit_per_min": matched_key.rate_limit_per_min,
                "expires_at": matched_key.expires_at.isoformat(),
            }

    async def revoke_key(self, key_id: str) -> bool:
        """Revoke an API key.

        Args:
            key_id: The key ID to revoke.

        Returns:
            True if revoked, False if not found.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                update(ApiKey).where(ApiKey.key_id == key_id).values(is_revoked=True)
            )
            await session.commit()

            if result.rowcount and result.rowcount > 0:
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
        async with self._pool.session() as session:
            if include_revoked:
                result = await session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
            else:
                result = await session.execute(
                    select(ApiKey)
                    .where(ApiKey.is_revoked == False)  # noqa: E712
                    .order_by(ApiKey.created_at.desc())
                )

            keys = result.scalars().all()
            return [
                {
                    "key_id": k.key_id,
                    "scopes": k.scopes,
                    "rate_limit_per_min": k.rate_limit_per_min,
                    "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                    "is_revoked": k.is_revoked,
                    "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                    "created_by": k.created_by,
                    "created_at": k.created_at.isoformat() if k.created_at else None,
                }
                for k in keys
            ]

    async def get_rate_limit(self, key_id: str) -> int:
        """Get the rate limit for a specific key.

        Args:
            key_id: The key ID.

        Returns:
            Max requests per minute.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(ApiKey.rate_limit_per_min).where(ApiKey.key_id == key_id)
            )
            row = result.scalar_one_or_none()
            return row if row is not None else 100

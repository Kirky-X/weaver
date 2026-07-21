# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""API Key management service.

Provides:
- Multi-key support with scopes and expiry
- bcrypt-hashed key storage
- Key creation, validation, and revocation
- Rate limit configuration per key

Implements: Weaver-数据库设计文档 §1.6.3
"""

from __future__ import annotations

import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from sqlalchemy import select, update

from core.db import ApiKey
from core.observability import get_logger
from core.observability.metrics import metrics
from core.protocols import RelationalPool

log = get_logger(__name__)

# Prometheus histogram for API key validation duration
_api_key_validation_duration = metrics.api_key_validation_duration_seconds

# New format: weaver_{8hex}_{16hex} (32 chars total, key_id = 8 hex chars)
# Shorter format requested for usability while keeping O(1) direct lookup.
_NEW_KEY_PATTERN = re.compile(r"^weaver_([0-9a-f]{8})_[0-9a-f]{16}$")
# Old format: weaver_key_{8-16hex}_{secret} (76+ chars, key_id = key_{8-16hex})
# Kept for backward compatibility with existing keys.
_OLD_KEY_PATTERN = re.compile(r"^weaver_(key_[0-9a-f]{8,16})_.+$")


def _prehash_key(key_value: str) -> bytes:
    """Pre-hash API key with SHA-256 before bcrypt.

    bcrypt has a 72-byte input limit. The API key format
    ``weaver_{key_id}_{secret}`` can exceed this (76+ bytes).
    SHA-256 output is always 32 bytes, well within the limit.

    Args:
        key_value: Raw API key string.

    Returns:
        SHA-256 hex digest encoded to bytes (64 bytes, ASCII-safe).
    """
    import hashlib

    return hashlib.sha256(key_value.encode()).hexdigest().encode()


class ApiKeyManager:
    """API Key lifecycle management with bcrypt hashing and ORM.

    Implements: Weaver-数据库设计文档 §1.6.3
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    @staticmethod
    def _extract_key_id(key_value: str) -> str | None:
        """Extract key_id from key_value if it uses a recognized format.

        New format (32 chars): weaver_{8hex}_{16hex} — key_id = 8 hex
        Old format (76+ chars): weaver_key_{8-16hex}_{secret} — key_id = key_{8-16hex}
        Legacy format: weaver_{uuid_hex} (no key_id embedded)

        Args:
            key_value: Raw API key string.

        Returns:
            Extracted key_id if recognized format, None if legacy/unknown.
        """
        if not key_value or not key_value.startswith("weaver_"):
            return None
        # Try new format first (32 chars)
        match = _NEW_KEY_PATTERN.match(key_value)
        if match:
            return match.group(1)
        # Fall back to old format (76+ chars)
        match = _OLD_KEY_PATTERN.match(key_value)
        return match.group(1) if match else None

    @staticmethod
    def _hash_key(key_value: str) -> str:
        """Hash API key using bcrypt with SHA-256 pre-hashing.

        Pre-hashes with SHA-256 to handle keys longer than bcrypt's
        72-byte input limit.

        Args:
            key_value: Raw API key string.

        Returns:
            bcrypt hash string (60 chars, starts with $2b$).
        """
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(_prehash_key(key_value), salt).decode()

    @staticmethod
    def _verify_key(key_value: str, key_hash: str) -> bool:
        """Verify API key against bcrypt hash.

        Pre-hashes the key with SHA-256 before bcrypt verification
        to match the hashing in :meth:`_hash_key`.

        Args:
            key_value: Raw API key string.
            key_hash: Stored bcrypt hash.

        Returns:
            True if key matches hash.
        """
        return bcrypt.checkpw(_prehash_key(key_value), key_hash.encode())

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
        # New 32-char format: weaver_{8hex}_{16hex}
        # key_id = 8 hex chars (4 bytes → 16^8 = 4G possibilities)
        # secret = 16 hex chars (8 bytes → 64 bits entropy)
        key_id = secrets.token_hex(4)
        key_value = f"weaver_{key_id}_{secrets.token_hex(8)}"
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

        Uses key_id extraction for O(1) direct lookup when possible.
        Falls back to O(n) scan for old-format keys without key_id prefix.

        Args:
            key_value: The raw API key to validate.

        Returns:
            Key info dict if valid, None if invalid/expired/revoked.
        """
        start_time = time.monotonic()
        extracted_key_id = self._extract_key_id(key_value)

        async with self._pool.session() as session:
            matched_key: ApiKey | None = None
            method: str = "scan"  # default fallback

            if extracted_key_id is not None:
                # O(1) direct lookup by key_id
                method = "direct"
                result = await session.execute(
                    select(ApiKey).where(ApiKey.key_id == extracted_key_id)
                )
                candidate = result.scalar_one_or_none()

                if candidate is not None:
                    # Check revoked first
                    if candidate.is_revoked:
                        elapsed = time.monotonic() - start_time
                        _api_key_validation_duration.labels(method=method).observe(elapsed)
                        return None
                    # Check rotated_to — rotated keys are no longer valid
                    # even though is_revoked may still be False (race window
                    # before atomic rotation completes).
                    if getattr(candidate, "rotated_to", None):
                        log.warning(
                            "api_key_rotated_rejected",
                            key_id=candidate.key_id,
                            rotated_to=candidate.rotated_to,
                        )
                        elapsed = time.monotonic() - start_time
                        _api_key_validation_duration.labels(method=method).observe(elapsed)
                        return None
                    # bcrypt verify
                    if self._verify_key(key_value, candidate.key_hash):
                        matched_key = candidate
                    # key_id found but bcrypt mismatch → no fallback, fail fast

            if matched_key is None and extracted_key_id is None:
                # Old format key: fall back to O(n) scan
                method = "scan"
                result = await session.execute(
                    select(ApiKey).where(ApiKey.is_revoked == False)  # noqa: E712
                )
                candidates = result.scalars().all()

                for candidate in candidates:
                    if getattr(candidate, "rotated_to", None):
                        continue  # skip rotated keys
                    if self._verify_key(key_value, candidate.key_hash):
                        matched_key = candidate
                        break

            if matched_key is None:
                elapsed = time.monotonic() - start_time
                _api_key_validation_duration.labels(method=method).observe(elapsed)
                return None

            # Check expiry
            if matched_key.expires_at < datetime.now(UTC):
                log.warning("api_key_expired", key_id=matched_key.key_id)
                elapsed = time.monotonic() - start_time
                _api_key_validation_duration.labels(method=method).observe(elapsed)
                return None

            # Update last_used_at
            await session.execute(
                update(ApiKey)
                .where(ApiKey.key_id == matched_key.key_id)
                .values(last_used_at=datetime.now(UTC))
            )
            await session.commit()

            elapsed = time.monotonic() - start_time
            _api_key_validation_duration.labels(method=method).observe(elapsed)

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

    async def _fetch_key(self, key_id: str) -> ApiKey | None:
        """Fetch an API key by key_id.

        Args:
            key_id: The key ID to fetch.

        Returns:
            ApiKey instance or None.
        """
        async with self._pool.session() as session:
            result = await session.execute(select(ApiKey).where(ApiKey.key_id == key_id))
            return result.scalar_one_or_none()

    async def rotate_key(self, key_id: str) -> dict[str, Any] | None:
        """Rotate an API key, creating a replacement and marking the old one.

        Creates a new key with the same scopes and rate limit as the old key
        and atomically marks the old key as rotated+revoked in a single
        transaction, eliminating the window where both old and new keys are
        valid simultaneously (CWE-362 fix).

        The fetch + insert + update is performed inside a single transaction
        using ``SELECT ... FOR UPDATE`` on the old key. This closes the TOCTOU
        window where two concurrent ``rotate_key`` calls for the same key_id
        would each read an unrotated old_key, then both insert a new key and
        clobber each other's ``rotated_to`` reference — leaving one new key as
        an orphan. With row-level locking, the second caller blocks until the
        first commits, then observes ``is_revoked=True`` / ``rotated_to != None``
        and bails out cleanly.

        Args:
            key_id: The key ID to rotate.

        Returns:
            New key info dict if rotated, None if key not found, already
            revoked, or already rotated.

        """
        # Build new key material
        new_key_id = secrets.token_hex(4)
        new_key_value = f"weaver_{new_key_id}_{secrets.token_hex(8)}"
        new_expires_at = datetime.now(UTC) + timedelta(days=90)
        new_key_hash = self._hash_key(new_key_value)

        # Single atomic transaction: SELECT ... FOR UPDATE + insert new key +
        # revoke+rotate old key. If any step fails, all roll back — no
        # half-rotated state, no orphaned new keys.
        async with self._pool.session() as session:
            # Lock the old key row for the duration of this transaction so
            # concurrent rotate_key / revoke_key callers cannot interleave.
            # with_for_update() emits SELECT ... FOR UPDATE on PG;
            # DuckDB falls back to a no-op lock (single-writer model).
            result = await session.execute(
                select(ApiKey).where(ApiKey.key_id == key_id).with_for_update()
            )
            old_key = result.scalar_one_or_none()

            if old_key is None:
                log.warning("api_key_rotation_failed_not_found", key_id=key_id)
                return None

            if old_key.is_revoked:
                log.warning(
                    "api_key_rotation_failed_already_revoked",
                    key_id=key_id,
                )
                return None

            if old_key.rotated_to is not None:
                log.warning(
                    "api_key_rotation_failed_already_rotated",
                    key_id=key_id,
                    rotated_to=old_key.rotated_to,
                )
                return None

            # Insert new key
            new_api_key = ApiKey(
                key_id=new_key_id,
                key_hash=new_key_hash,
                scopes=old_key.scopes,
                rate_limit_per_min=old_key.rate_limit_per_min,
                expires_at=new_expires_at,
                created_by=f"rotation:{key_id}",
            )
            session.add(new_api_key)

            # Mark old key as rotated atomically. validate_key() rejects any
            # key whose ``rotated_to`` is non-null (see api_key_manager.validate_key
            # around line 214), so setting ``rotated_to`` is sufficient to close
            # the window where both old and new keys are valid simultaneously
            # (CWE-362). We intentionally do NOT set ``is_revoked=True`` here
            # because ``is_revoked`` is reserved for explicit revocation
            # (revoke_key) and is the field audit logs key off of to flag
            # operator-initiated revocations vs. scheduled rotations.
            await session.execute(
                update(ApiKey).where(ApiKey.key_id == key_id).values(rotated_to=new_key_id)
            )
            await session.commit()

        log.info(
            "api_key_rotated",
            old_key_id=key_id,
            new_key_id=new_key_id,
        )

        return {
            "key_id": new_key_id,
            "key_value": new_key_value,
            "scopes": old_key.scopes,
            "rate_limit_per_min": old_key.rate_limit_per_min,
            "expires_at": new_expires_at.isoformat(),
        }

    async def check_expiring_keys(self, days_before: int = 7) -> int:
        """Check for keys expiring within days_before days and auto-rotate them.

        Args:
            days_before: Number of days before expiry to trigger rotation.

        Returns:
            Number of keys rotated.
        """
        threshold = datetime.now(UTC) + timedelta(days=days_before)

        async with self._pool.session() as session:
            result = await session.execute(
                select(ApiKey).where(
                    ApiKey.is_revoked == False,  # noqa: E712
                    ApiKey.rotated_to.is_(None),
                    ApiKey.expires_at <= threshold,
                    ApiKey.expires_at > datetime.now(UTC),
                )
            )
            expiring_keys = result.scalars().all()

        rotated_count = 0
        for key in expiring_keys:
            try:
                new_key = await self.rotate_key(key.key_id)
                if new_key:
                    rotated_count += 1
            except Exception as exc:
                log.warning(
                    "api_key_auto_rotation_failed",
                    key_id=key.key_id,
                    error=str(exc),
                )

        if rotated_count > 0:
            log.info("api_key_auto_rotation_complete", count=rotated_count)

        return rotated_count

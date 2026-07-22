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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
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


class KeyOpStatus(str, Enum):
    """Outcome of a key management operation (revoke/rotate).

    Replaces the previous bool/dict return types so callers can distinguish
    not_found / forbidden / already_revoked / ok without raising HTTPException
    inside the service layer (vuln-0009 fix).
    """

    OK = "ok"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    ALREADY_REVOKED = "already_revoked"
    ALREADY_ROTATED = "already_rotated"


@dataclass
class KeyOpResult:
    """Result of a key management operation.

    Attributes:
        status: Outcome status.
        data: For rotate_key OK, contains the new key info dict. Else None.
    """

    status: KeyOpStatus
    data: dict[str, Any] | None = None


# Actor identifiers for audit log and ownership check.
# These are the only values that bypass ownership check in revoke_key/rotate_key.
# IMPORTANT: verify_admin_api_key and verify_api_key MUST return these exact
# strings — drift between producer and consumer would silently lock out all
# admins (silent failure, no error raised).
ENV_ADMIN_ACTOR = "env-admin"
SYSTEM_ACTOR = "system"
_SUPER_ADMIN_ACTORS: frozenset[str] = frozenset({ENV_ADMIN_ACTOR, SYSTEM_ACTOR})

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
    def _select_key_for_update(session: Any, key_id: str) -> Any:
        """Build SELECT ApiKey by key_id, with FOR UPDATE on PostgreSQL only.

        DuckDB 不支持 ``FOR UPDATE`` 锁定子句（``Parser Error: SELECT
        locking clause is not supported!``），跳过行级锁。DuckDB 乐观并发
        控制（OCC）在 commit 时检测写-写冲突，跳过 ``FOR UPDATE`` 不影响
        并发安全性。
        """
        stmt = select(ApiKey).where(ApiKey.key_id == key_id)
        try:
            if session.get_bind().dialect.name != "duckdb":
                stmt = stmt.with_for_update()
        except AttributeError:
            pass
        return stmt

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

    async def revoke_key(self, key_id: str, actor: str = "env-admin") -> KeyOpResult:
        """Revoke an API key with ownership check (vuln-0009 fix: CWE-639).

        Only the key's creator (``created_by``) or a super-admin
        (``env-admin`` / ``system``) can revoke a key. This closes the IDOR
        where any admin could revoke any other admin's key.

        Args:
            key_id: The key ID to revoke.
            actor: Admin identifier performing the operation. Super-admins
                (``env-admin``, ``system``) bypass the ownership check.

        Returns:
            KeyOpResult with status:
                OK — revoked successfully.
                NOT_FOUND — key_id does not exist.
                ALREADY_REVOKED — key was already revoked (idempotent no-op).
                FORBIDDEN — actor is not the owner nor a super-admin.
        """
        async with self._pool.session() as session:
            # Using FOR UPDATE to align with rotate_key and prevent concurrent
            # revoke+rotate from producing misleading OK status (MED-004 fix).
            # DuckDB 下降级为普通 SELECT（单写者模型已保证串行）。
            fetch_result = await session.execute(self._select_key_for_update(session, key_id))
            target = fetch_result.scalar_one_or_none()

            if target is None:
                return KeyOpResult(status=KeyOpStatus.NOT_FOUND)

            if target.is_revoked:
                return KeyOpResult(status=KeyOpStatus.ALREADY_REVOKED)

            # Ownership check (vuln-0009): super-admins bypass; otherwise
            # actor must match the key's created_by.
            if actor not in _SUPER_ADMIN_ACTORS and target.created_by != actor:
                log.warning(
                    "api_key_revoke_forbidden",
                    key_id=key_id,
                    actor=actor,
                    owner=target.created_by,
                )
                return KeyOpResult(status=KeyOpStatus.FORBIDDEN)

            await session.execute(
                update(ApiKey).where(ApiKey.key_id == key_id).values(is_revoked=True)
            )
            await session.commit()

            log.info("api_key_revoked", key_id=key_id, actor=actor)
            return KeyOpResult(status=KeyOpStatus.OK)

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

    async def rotate_key(self, key_id: str, actor: str = "env-admin") -> KeyOpResult:
        """Rotate an API key with ownership check (vuln-0009 fix: CWE-639).

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

        Ownership check (vuln-0009): only the key's creator or a super-admin
        (``env-admin`` / ``system``) can rotate a key. The ownership check runs
        AFTER the FOR UPDATE lock is acquired, so a concurrent caller that
        passes ownership cannot race with one that fails it.

        Args:
            key_id: The key ID to rotate.
            actor: Admin identifier performing the operation. Super-admins
                (``env-admin``, ``system``) bypass the ownership check.

        Returns:
            KeyOpResult with status:
                OK — rotated successfully; ``data`` holds the new key info.
                NOT_FOUND — key_id does not exist.
                FORBIDDEN — actor is not the owner nor a super-admin.
                ALREADY_REVOKED — key was already revoked.
                ALREADY_ROTATED — key was already rotated.

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
            # DuckDB 下降级为普通 SELECT（单写者模型已保证串行）。
            result = await session.execute(self._select_key_for_update(session, key_id))
            old_key = result.scalar_one_or_none()

            if old_key is None:
                log.warning("api_key_rotation_failed_not_found", key_id=key_id)
                return KeyOpResult(status=KeyOpStatus.NOT_FOUND)

            # Ownership check (vuln-0009): runs after FOR UPDATE so the
            # ownership decision is consistent with the row state being
            # rotated. Super-admins bypass; otherwise actor must match
            # created_by.
            if actor not in _SUPER_ADMIN_ACTORS and old_key.created_by != actor:
                log.warning(
                    "api_key_rotation_forbidden",
                    key_id=key_id,
                    actor=actor,
                    owner=old_key.created_by,
                )
                return KeyOpResult(status=KeyOpStatus.FORBIDDEN)

            if old_key.is_revoked:
                log.warning(
                    "api_key_rotation_failed_already_revoked",
                    key_id=key_id,
                )
                return KeyOpResult(status=KeyOpStatus.ALREADY_REVOKED)

            if old_key.rotated_to is not None:
                log.warning(
                    "api_key_rotation_failed_already_rotated",
                    key_id=key_id,
                    rotated_to=old_key.rotated_to,
                )
                return KeyOpResult(status=KeyOpStatus.ALREADY_ROTATED)

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
            actor=actor,
        )

        return KeyOpResult(
            status=KeyOpStatus.OK,
            data={
                "key_id": new_key_id,
                "key_value": new_key_value,
                "scopes": old_key.scopes,
                "rate_limit_per_min": old_key.rate_limit_per_min,
                "expires_at": new_expires_at.isoformat(),
            },
        )

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
                # Auto-rotation runs as the "system" super-admin so it can
                # rotate any key regardless of created_by (vuln-0009).
                result = await self.rotate_key(key.key_id, actor="system")
                if result.status is KeyOpStatus.OK:
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

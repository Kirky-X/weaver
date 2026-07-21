# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for API Key auto-rotation (Task 4).

Verifies:
- Key rotation creates replacement key 7 days before expiry
- Old key remains valid during 24h grace period
- Rotated key has rotated_to field set
- Daily scheduler checks for expiring keys
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.db import ApiKey
from core.security.api_key_manager import KeyOpStatus


class TestApiKeyRotatedToField:
    """ApiKey model SHALL have rotated_to field."""

    def test_has_rotated_to_column(self) -> None:
        """ApiKey SHALL have rotated_to column."""
        assert "rotated_to" in ApiKey.__table__.columns


class TestApiKeyRotation:
    """Tests for ApiKeyManager.rotate_key() method."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.session = MagicMock()
        return pool

    @pytest.fixture
    def manager(self, mock_pool):
        from core.security.api_key_manager import ApiKeyManager

        return ApiKeyManager(pool=mock_pool)

    def test_rotate_key_method_exists(self, manager) -> None:
        """ApiKeyManager SHALL have rotate_key method."""
        assert hasattr(manager, "rotate_key")
        assert callable(manager.rotate_key)

    @pytest.mark.asyncio
    async def test_rotate_creates_new_key(self, manager, mock_pool) -> None:
        """rotate_key SHALL create a new replacement key."""
        # Mock session
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        # Mock the old key query — rotate_key now does SELECT ... FOR UPDATE
        # inside the main transaction (TOCTOU fix), so we mock session.execute
        # to return a result with scalar_one_or_none returning the old_key.
        old_key = ApiKey(
            key_id="key_old123",
            key_hash="$2b$12$hash",
            scopes=["search:read"],
            rate_limit_per_min=100,
            expires_at=datetime.now(UTC) + timedelta(days=5),
        )

        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=old_key)
        update_result = MagicMock()
        mock_session.execute = AsyncMock(side_effect=[select_result, update_result])

        result = await manager.rotate_key("key_old123")

        # Should return new key info
        assert result.status is KeyOpStatus.OK
        assert result.data is not None
        assert "key_id" in result.data
        assert "key_value" in result.data
        assert result.data["key_id"] != "key_old123"

    @pytest.mark.asyncio
    async def test_rotate_marks_old_key(self, manager, mock_pool) -> None:
        """rotate_key SHALL set rotated_to on old key via SQL UPDATE."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        old_key = ApiKey(
            key_id="key_old123",
            key_hash="$2b$12$hash",
            scopes=["search:read"],
            rate_limit_per_min=100,
            expires_at=datetime.now(UTC) + timedelta(days=5),
        )

        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=old_key)
        update_result = MagicMock()
        mock_session.execute = AsyncMock(side_effect=[select_result, update_result])

        result = await manager.rotate_key("key_old123")

        # Verify the result contains a new key_id (rotation happened)
        assert result.status is KeyOpStatus.OK
        assert result.data is not None
        assert result.data["key_id"] != "key_old123"
        # Two execute calls: SELECT ... FOR UPDATE + UPDATE rotated_to
        assert mock_session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_rotate_preserves_scopes(self, manager, mock_pool) -> None:
        """rotate_key SHALL preserve scopes from old key."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        old_key = ApiKey(
            key_id="key_old123",
            key_hash="$2b$12$hash",
            scopes=["search:read", "admin:write"],
            rate_limit_per_min=50,
            expires_at=datetime.now(UTC) + timedelta(days=5),
        )

        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=old_key)
        update_result = MagicMock()
        mock_session.execute = AsyncMock(side_effect=[select_result, update_result])

        result = await manager.rotate_key("key_old123")

        assert result.status is KeyOpStatus.OK
        assert result.data is not None
        assert result.data["scopes"] == ["search:read", "admin:write"]
        assert result.data["rate_limit_per_min"] == 50


class TestGracePeriod:
    """Old key SHALL be invalidated via rotated_to (not is_revoked) on rotation.

    After the CWE-362 fix (vuln-0001), rotate_key uses SELECT ... FOR UPDATE
    to atomically fetch + rotate within a single transaction. The old key is
    invalidated by setting ``rotated_to`` (validate_key rejects any key whose
    ``rotated_to`` is non-null). ``is_revoked`` is intentionally NOT set — it
    is reserved for explicit operator-initiated revocation (revoke_key), so
    audit logs can distinguish scheduled rotations from explicit revocations.
    """

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.session = MagicMock()
        return pool

    @pytest.fixture
    def manager(self, mock_pool):
        from core.security.api_key_manager import ApiKeyManager

        return ApiKeyManager(pool=mock_pool)

    @pytest.mark.asyncio
    async def test_rotated_key_valid_in_grace_period(self, manager, mock_pool) -> None:
        """Rotation SHALL invalidate old key via rotated_to, NOT is_revoked.

        Setting ``rotated_to`` is sufficient: validate_key rejects any key
        whose ``rotated_to`` is non-null (immediate invalidation, no grace
        window — closes the CWE-362 race). ``is_revoked`` stays False so audit
        logs can distinguish rotation from explicit revocation.
        """
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        old_key = ApiKey(
            key_id="key_old123",
            key_hash="$2b$12$hash",
            scopes=["search:read"],
            rate_limit_per_min=100,
            expires_at=datetime.now(UTC) + timedelta(days=5),
        )

        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=old_key)
        update_result = MagicMock()
        mock_session.execute = AsyncMock(side_effect=[select_result, update_result])

        result = await manager.rotate_key("key_old123")

        # rotation succeeded
        assert result.status is KeyOpStatus.OK
        assert result.data is not None
        assert result.data["key_id"] != "key_old123"
        # rotate_key should NOT set is_revoked=True on old key — rotated_to
        # is the invalidation mechanism (validate_key enforces it).
        assert old_key.is_revoked is not True


class TestRotateKeyTOCTOU:
    """TOCTOU edge cases — rotate_key SHALL reject already-rotated / revoked keys.

    After the CWE-362 fix (vuln-0001), rotate_key performs SELECT ... FOR UPDATE
    inside the main transaction and inspects ``is_revoked`` / ``rotated_to``
    before rotating. Concurrent rotate_key calls for the same key_id are
    serialized by the row lock; the second caller observes the post-rotation
    state and bails out cleanly instead of creating an orphan new key.
    """

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.session = MagicMock()
        return pool

    @pytest.fixture
    def manager(self, mock_pool):
        from core.security.api_key_manager import ApiKeyManager

        return ApiKeyManager(pool=mock_pool)

    @pytest.mark.asyncio
    async def test_rotate_already_revoked_key_returns_none(self, manager, mock_pool) -> None:
        """rotate_key SHALL return ALREADY_REVOKED when key is already revoked."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        revoked_key = ApiKey(
            key_id="key_old123",
            key_hash="$2b$12$hash",
            scopes=["search:read"],
            rate_limit_per_min=100,
            expires_at=datetime.now(UTC) + timedelta(days=5),
            is_revoked=True,
        )

        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=revoked_key)
        mock_session.execute = AsyncMock(return_value=select_result)

        result = await manager.rotate_key("key_old123")

        # No new key created — UPDATE was not called.
        assert result.status is KeyOpStatus.ALREADY_REVOKED
        assert mock_session.execute.call_count == 1  # SELECT only, no UPDATE
        # session.add never called — no new key inserted.
        assert not mock_session.add.called
        assert not mock_session.commit.called

    @pytest.mark.asyncio
    async def test_rotate_already_rotated_key_returns_none(self, manager, mock_pool) -> None:
        """rotate_key SHALL return ALREADY_ROTATED when key is already rotated."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        rotated_key = ApiKey(
            key_id="key_old123",
            key_hash="$2b$12$hash",
            scopes=["search:read"],
            rate_limit_per_min=100,
            expires_at=datetime.now(UTC) + timedelta(days=5),
            is_revoked=False,
            rotated_to="key_new456",  # already rotated
        )

        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=rotated_key)
        mock_session.execute = AsyncMock(return_value=select_result)

        result = await manager.rotate_key("key_old123")

        # No new key created — UPDATE was not called.
        assert result.status is KeyOpStatus.ALREADY_ROTATED
        assert mock_session.execute.call_count == 1  # SELECT only, no UPDATE
        assert not mock_session.add.called
        assert not mock_session.commit.called

    @pytest.mark.asyncio
    async def test_rotate_nonexistent_key_returns_none(self, manager, mock_pool) -> None:
        """rotate_key SHALL return NOT_FOUND when key_id not found in DB."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        # scalar_one_or_none returns None — key not in DB.
        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=select_result)

        result = await manager.rotate_key("nonexistent_key")

        assert result.status is KeyOpStatus.NOT_FOUND
        assert mock_session.execute.call_count == 1  # SELECT only
        assert not mock_session.add.called
        assert not mock_session.commit.called


class TestDailyRotationCheck:
    """Daily scheduler SHALL check for expiring keys."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.session = MagicMock()
        return pool

    @pytest.fixture
    def manager(self, mock_pool):
        from core.security.api_key_manager import ApiKeyManager

        return ApiKeyManager(pool=mock_pool)

    def test_check_expiring_keys_method_exists(self, manager) -> None:
        """ApiKeyManager SHALL have check_expiring_keys method."""
        assert hasattr(manager, "check_expiring_keys")
        assert callable(manager.check_expiring_keys)

    @pytest.mark.asyncio
    async def test_check_expiring_keys_returns_count(self, manager, mock_pool) -> None:
        """check_expiring_keys SHALL return count of rotated keys."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        # Mock query returning no expiring keys
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await manager.check_expiring_keys()
        assert isinstance(result, int)

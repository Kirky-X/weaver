# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Ownership check tests for ApiKeyManager.revoke_key / rotate_key.

Verifies vuln-0009 fix (CWE-639 IDOR): any admin could previously revoke
or rotate any other admin's key. Now the manager enforces ownership —
only the key's creator or a super-admin ("env-admin" / "system") can
operate on it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.security.api_key_manager import (
    ApiKeyManager,
    KeyOpResult,
    KeyOpStatus,
)


class TestRevokeKeyOwnership:
    """revoke_key SHALL enforce ownership check (vuln-0009)."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.session = MagicMock()
        return pool

    @pytest.fixture
    def manager(self, mock_pool):
        return ApiKeyManager(pool=mock_pool)

    def _make_session(self, mock_pool, target_key):
        """Build a mock session returning target_key from SELECT."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)
        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=target_key)
        update_result = MagicMock()
        mock_session.execute = AsyncMock(side_effect=[select_result, update_result])
        return mock_session

    def _make_target(self, created_by="alice", is_revoked=False):
        target = MagicMock()
        target.key_id = "key_target"
        target.created_by = created_by
        target.is_revoked = is_revoked
        target.rotated_to = None
        return target

    @pytest.mark.asyncio
    async def test_revoke_returns_forbidden_when_actor_not_owner(self, manager, mock_pool) -> None:
        """Non-owner, non-super-admin actor → FORBIDDEN."""
        target = self._make_target(created_by="alice")
        self._make_session(mock_pool, target)

        result = await manager.revoke_key("key_target", actor="bob")

        assert result.status is KeyOpStatus.FORBIDDEN

    @pytest.mark.asyncio
    async def test_revoke_returns_ok_when_actor_is_env_admin(self, manager, mock_pool) -> None:
        """env-admin (super-admin) bypasses ownership check."""
        target = self._make_target(created_by="alice")
        self._make_session(mock_pool, target)

        result = await manager.revoke_key("key_target", actor="env-admin")

        assert result.status is KeyOpStatus.OK

    @pytest.mark.asyncio
    async def test_revoke_returns_ok_when_actor_is_system(self, manager, mock_pool) -> None:
        """system (auto-rotation) bypasses ownership check."""
        target = self._make_target(created_by="alice")
        self._make_session(mock_pool, target)

        result = await manager.revoke_key("key_target", actor="system")

        assert result.status is KeyOpStatus.OK

    @pytest.mark.asyncio
    async def test_revoke_returns_ok_when_actor_is_owner(self, manager, mock_pool) -> None:
        """Actor matching created_by → OK."""
        target = self._make_target(created_by="alice")
        self._make_session(mock_pool, target)

        result = await manager.revoke_key("key_target", actor="alice")

        assert result.status is KeyOpStatus.OK

    @pytest.mark.asyncio
    async def test_revoke_returns_not_found(self, manager, mock_pool) -> None:
        """Key not in DB → NOT_FOUND."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)
        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=select_result)

        result = await manager.revoke_key("nonexistent", actor="env-admin")

        assert result.status is KeyOpStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_revoke_returns_already_revoked(self, manager, mock_pool) -> None:
        """Already-revoked key → ALREADY_REVOKED."""
        target = self._make_target(created_by="alice", is_revoked=True)
        self._make_session(mock_pool, target)

        result = await manager.revoke_key("key_target", actor="env-admin")

        assert result.status is KeyOpStatus.ALREADY_REVOKED

    @pytest.mark.asyncio
    async def test_revoke_does_not_update_when_forbidden(self, manager, mock_pool) -> None:
        """FORBIDDEN SHALL NOT execute the UPDATE statement."""
        target = self._make_target(created_by="alice")
        mock_session = self._make_session(mock_pool, target)

        await manager.revoke_key("key_target", actor="bob")

        # Only the SELECT should have run, not the UPDATE.
        assert mock_session.execute.call_count == 1


class TestRotateKeyOwnership:
    """rotate_key SHALL enforce ownership check (vuln-0009)."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.session = MagicMock()
        return pool

    @pytest.fixture
    def manager(self, mock_pool):
        return ApiKeyManager(pool=mock_pool)

    def _make_session(self, mock_pool, target_key):
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)
        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=target_key)
        update_result = MagicMock()
        mock_session.execute = AsyncMock(side_effect=[select_result, update_result])
        return mock_session

    def _make_target(self, created_by="alice"):
        target = MagicMock()
        target.key_id = "key_target"
        target.created_by = created_by
        target.scopes = ["search:read"]
        target.rate_limit_per_min = 100
        target.expires_at = datetime.now(UTC) + timedelta(days=5)
        target.is_revoked = False
        target.rotated_to = None
        return target

    @pytest.mark.asyncio
    async def test_rotate_returns_forbidden_when_actor_not_owner(self, manager, mock_pool) -> None:
        """Non-owner, non-super-admin actor → FORBIDDEN."""
        target = self._make_target(created_by="alice")
        self._make_session(mock_pool, target)

        result = await manager.rotate_key("key_target", actor="bob")

        assert result.status is KeyOpStatus.FORBIDDEN
        assert result.data is None

    @pytest.mark.asyncio
    async def test_rotate_returns_ok_when_actor_is_env_admin(self, manager, mock_pool) -> None:
        """env-admin bypasses ownership check."""
        target = self._make_target(created_by="alice")
        self._make_session(mock_pool, target)

        result = await manager.rotate_key("key_target", actor="env-admin")

        assert result.status is KeyOpStatus.OK
        assert result.data is not None
        assert "key_id" in result.data
        assert result.data["key_id"] != "key_target"

    @pytest.mark.asyncio
    async def test_rotate_returns_ok_when_actor_is_owner(self, manager, mock_pool) -> None:
        """Actor matching created_by → OK."""
        target = self._make_target(created_by="alice")
        self._make_session(mock_pool, target)

        result = await manager.rotate_key("key_target", actor="alice")

        assert result.status is KeyOpStatus.OK
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_rotate_returns_not_found(self, manager, mock_pool) -> None:
        """Key not in DB → NOT_FOUND."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)
        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=select_result)

        result = await manager.rotate_key("nonexistent", actor="env-admin")

        assert result.status is KeyOpStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_rotate_does_not_update_when_forbidden(self, manager, mock_pool) -> None:
        """FORBIDDEN SHALL NOT insert new key or update old key."""
        target = self._make_target(created_by="alice")
        mock_session = self._make_session(mock_pool, target)

        await manager.rotate_key("key_target", actor="bob")

        # Only the SELECT ... FOR UPDATE should have run.
        assert mock_session.execute.call_count == 1
        # No new key added.
        assert mock_session.add.call_count == 0

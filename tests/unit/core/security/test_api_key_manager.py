# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for ApiKeyManager: bcrypt hashing and ORM-based operations."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from core.db import ApiKey
from core.security.api_key_manager import ApiKeyManager
from tests.helpers import create_mock_relational_pool


@pytest.fixture
def mock_pool() -> MagicMock:
    """Create a mock RelationalPool with async session support."""
    return create_mock_relational_pool()


@pytest.fixture
def manager(mock_pool: MagicMock) -> ApiKeyManager:
    """Create ApiKeyManager with mock pool."""
    return ApiKeyManager(mock_pool)


class TestCreateKey:
    """Tests for ApiKeyManager.create_key."""

    async def test_returns_key_value(self, manager: ApiKeyManager) -> None:
        """create_key returns key_value that can be used for authentication."""
        result = await manager.create_key()
        assert "key_value" in result
        assert result["key_value"].startswith("weaver_")

    async def test_returns_key_id(self, manager: ApiKeyManager) -> None:
        """create_key returns a key_id."""
        result = await manager.create_key()
        assert "key_id" in result
        assert result["key_id"]

    async def test_default_scopes(self, manager: ApiKeyManager) -> None:
        """Default scopes is ['search:read']."""
        result = await manager.create_key()
        assert result["scopes"] == ["search:read"]

    async def test_custom_scopes(self, manager: ApiKeyManager) -> None:
        """Custom scopes are stored."""
        result = await manager.create_key(scopes=["search:read", "admin"])
        assert result["scopes"] == ["search:read", "admin"]

    async def test_stores_bcrypt_hash(self, manager: ApiKeyManager, mock_pool: MagicMock) -> None:
        """Key hash stored in DB is bcrypt, not SHA-256."""
        result = await manager.create_key()
        session = mock_pool.session.return_value

        # Find the ApiKey object that was added to the session
        added_objects = [call[0][0] for call in session.add.call_args_list]
        api_key_obj = None
        for obj in added_objects:
            if isinstance(obj, ApiKey):
                api_key_obj = obj
                break

        assert api_key_obj is not None
        # bcrypt hash starts with $2b$ and is 60 chars
        assert api_key_obj.key_hash.startswith("$2b$")
        assert len(api_key_obj.key_hash) == 60

    async def test_bcrypt_hash_verifiable(
        self, manager: ApiKeyManager, mock_pool: MagicMock
    ) -> None:
        """Stored bcrypt hash can verify the original key."""
        result = await manager.create_key()
        session = mock_pool.session.return_value

        added_objects = [call[0][0] for call in session.add.call_args_list]
        api_key_obj = next(obj for obj in added_objects if isinstance(obj, ApiKey))

        # Verify the hash matches the key (using same pre-hash as production)
        assert ApiKeyManager._verify_key(result["key_value"], api_key_obj.key_hash)


class TestValidateKey:
    """Tests for ApiKeyManager.validate_key."""

    async def test_valid_key_returns_info(
        self, manager: ApiKeyManager, mock_pool: MagicMock
    ) -> None:
        """Valid key returns key info dict."""
        # Create a key first
        create_result = await manager.create_key()
        key_value = create_result["key_value"]
        key_id = create_result["key_id"]

        # Mock the session to return the stored ApiKey
        session = mock_pool.session.return_value
        added_objects = [call[0][0] for call in session.add.call_args_list]
        api_key_obj = next(obj for obj in added_objects if isinstance(obj, ApiKey))

        # New format keys use direct lookup (scalar_one_or_none)
        mock_direct_result = MagicMock()
        mock_direct_result.scalar_one_or_none.return_value = api_key_obj
        # Update result for last_used_at
        mock_update_result = MagicMock()
        session.execute.side_effect = [mock_direct_result, mock_update_result]

        result = await manager.validate_key(key_value)
        assert result is not None
        assert result["key_id"] == key_id

    async def test_invalid_key_returns_none(
        self, manager: ApiKeyManager, mock_pool: MagicMock
    ) -> None:
        """Invalid key returns None."""
        session = mock_pool.session.return_value
        # Old format key (no key_id prefix) → scan path
        mock_scan_result = MagicMock()
        mock_scan_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_scan_result

        result = await manager.validate_key("weaver_invalidkey")
        assert result is None


class TestRevokeKey:
    """Tests for ApiKeyManager.revoke_key."""

    async def test_revoke_sets_is_revoked(
        self, manager: ApiKeyManager, mock_pool: MagicMock
    ) -> None:
        """Revoke sets is_revoked to True."""
        session = mock_pool.session.return_value
        mock_result = MagicMock()
        mock_result.rowcount = 1
        session.execute.return_value = mock_result

        result = await manager.revoke_key("key_abc123")
        assert result is True


class TestListKeys:
    """Tests for ApiKeyManager.list_keys."""

    async def test_list_returns_dicts(self, manager: ApiKeyManager, mock_pool: MagicMock) -> None:
        """list_keys returns list of dicts."""
        session = mock_pool.session.return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        result = await manager.list_keys()
        assert isinstance(result, list)

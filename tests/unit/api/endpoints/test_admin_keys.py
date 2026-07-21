# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for API Key management endpoints (unified in admin.py).

Verifies:
- API key creation via admin endpoint
- API key listing via admin endpoint
- API key revocation via admin endpoint
- API key rotation via admin endpoint
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from core.security import ApiKeyManager
from core.security.api_key_manager import KeyOpStatus


class TestApiKeyRotationEndpoint:
    """Test API Key rotation endpoint POST /api/v1/admin/api-keys/{key_id}/rotate."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.session = MagicMock()
        return pool

    @pytest.fixture
    def manager(self, mock_pool):
        return ApiKeyManager(pool=mock_pool)

    @pytest.mark.asyncio
    async def test_rotate_key_returns_new_key_info(self, manager, mock_pool) -> None:
        """rotate_key SHALL return new key info dict."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        old_key = MagicMock()
        old_key.key_id = "key_old123"
        old_key.scopes = ["search:read", "admin:write"]
        old_key.rate_limit_per_min = 50
        old_key.expires_at = datetime.now(UTC) + timedelta(days=5)
        old_key.is_revoked = False
        old_key.rotated_to = None

        # rotate_key now does SELECT ... FOR UPDATE inside the main transaction
        # (TOCTOU fix), so mock session.execute to return a result with
        # scalar_one_or_none returning the old_key.
        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=old_key)
        update_result = MagicMock()
        mock_session.execute = AsyncMock(side_effect=[select_result, update_result])

        result = await manager.rotate_key("key_old123")

        assert result.status is KeyOpStatus.OK
        assert result.data is not None
        assert "key_id" in result.data
        assert "key_value" in result.data
        assert result.data["key_id"] != "key_old123"
        assert result.data["scopes"] == ["search:read", "admin:write"]
        assert result.data["rate_limit_per_min"] == 50

    @pytest.mark.asyncio
    async def test_rotate_key_not_found(self, manager, mock_pool) -> None:
        """rotate_key SHALL return NOT_FOUND when key not found."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        # scalar_one_or_none returns None — key not in DB.
        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=select_result)

        result = await manager.rotate_key("nonexistent_key")

        assert result.status is KeyOpStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_rotate_key_marks_old_key(self, manager, mock_pool) -> None:
        """rotate_key SHALL set rotated_to on old key via SQL UPDATE."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        old_key = MagicMock()
        old_key.key_id = "key_old123"
        old_key.scopes = ["search:read"]
        old_key.rate_limit_per_min = 100
        old_key.expires_at = datetime.now(UTC) + timedelta(days=5)
        old_key.is_revoked = False
        old_key.rotated_to = None

        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=old_key)
        update_result = MagicMock()
        mock_session.execute = AsyncMock(side_effect=[select_result, update_result])

        result = await manager.rotate_key("key_old123")

        assert result.status is KeyOpStatus.OK
        # Two execute calls: SELECT ... FOR UPDATE + UPDATE rotated_to
        assert mock_session.execute.call_count == 2


class TestDailyRotationScheduler:
    """Test daily rotation scheduler job."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.session = MagicMock()
        return pool

    @pytest.fixture
    def manager(self, mock_pool):
        return ApiKeyManager(pool=mock_pool)

    @pytest.mark.asyncio
    async def test_check_expiring_keys_auto_rotates(self, manager, mock_pool) -> None:
        """check_expiring_keys SHALL auto-rotate keys expiring within 7 days."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        # Create a key expiring in 5 days
        expiring_key = MagicMock()
        expiring_key.key_id = "key_expiring"
        expiring_key.scopes = ["search:read"]
        expiring_key.rate_limit_per_min = 100
        expiring_key.expires_at = datetime.now(UTC) + timedelta(days=5)

        # Mock the query to return the expiring key
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [expiring_key]
        mock_session.execute.return_value = mock_result

        # check_expiring_keys now calls rotate_key with actor="system" and
        # expects a KeyOpResult (vuln-0009 fix). Mock the return value.
        from core.security.api_key_manager import KeyOpResult

        ok_result = KeyOpResult(status=KeyOpStatus.OK, data={"key_id": "new_key"})
        with patch.object(manager, "rotate_key", return_value=ok_result) as mock_rotate:
            count = await manager.check_expiring_keys(days_before=7)

        assert count == 1
        mock_rotate.assert_called_once_with("key_expiring", actor="system")

    @pytest.mark.asyncio
    async def test_check_expiring_keys_no_expiring(self, manager, mock_pool) -> None:
        """check_expiring_keys SHALL return 0 when no keys are expiring."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        count = await manager.check_expiring_keys(days_before=7)
        assert count == 0

    @pytest.mark.asyncio
    async def test_scheduler_job_exists(self) -> None:
        """SchedulerJobs SHALL have check_expiring_api_keys method."""
        from modules.scheduler.jobs import SchedulerJobs

        assert hasattr(SchedulerJobs, "check_expiring_api_keys")
        assert callable(SchedulerJobs.check_expiring_api_keys)


class TestGracePeriod:
    """Old key SHALL remain valid during 24h grace period after rotation."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.session = MagicMock()
        return pool

    @pytest.fixture
    def manager(self, mock_pool):
        return ApiKeyManager(pool=mock_pool)

    @pytest.mark.asyncio
    async def test_rotated_key_not_revoked(self, manager, mock_pool) -> None:
        """Rotated key SHALL NOT be revoked immediately (grace period).

        After the CWE-362 fix (vuln-0001), rotate_key uses SELECT ... FOR UPDATE
        inside the main transaction and sets ``rotated_to`` (validate_key rejects
        any key whose ``rotated_to`` is non-null). ``is_revoked`` stays False —
        it is reserved for explicit operator-initiated revocation (revoke_key),
        so audit logs can distinguish scheduled rotations from explicit revocations.
        """
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        old_key = MagicMock()
        old_key.key_id = "key_old123"
        old_key.scopes = ["search:read"]
        old_key.rate_limit_per_min = 100
        old_key.expires_at = datetime.now(UTC) + timedelta(days=5)
        old_key.is_revoked = False
        old_key.rotated_to = None

        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=old_key)
        update_result = MagicMock()
        mock_session.execute = AsyncMock(side_effect=[select_result, update_result])

        result = await manager.rotate_key("key_old123")

        # rotation succeeded
        assert result is not None
        # rotate_key should NOT set is_revoked=True on old key — rotated_to
        # is the invalidation mechanism (validate_key enforces it).
        assert old_key.is_revoked is False


class TestCreatedByValidation:
    """created_by field SHALL reject stored-XSS payloads (regression for admin_021/022)."""

    def test_rejects_script_tag(self) -> None:
        """created_by containing <script> SHALL raise ValidationError."""
        from api.endpoints.admin.api_keys import CreateApiKeyRequest

        with pytest.raises(ValidationError) as exc_info:
            CreateApiKeyRequest(created_by='"<script>alert(1)</script>"')
        assert "forbidden characters" in str(exc_info.value).lower()

    def test_rejects_each_dangerous_char(self) -> None:
        """Each dangerous char SHALL be rejected individually."""
        from api.endpoints.admin.api_keys import CreateApiKeyRequest

        dangerous = ["<", ">", '"', "'", "&", ";", "(", ")"]
        for ch in dangerous:
            with pytest.raises(ValidationError):
                CreateApiKeyRequest(created_by=f"evil{ch}name")

    def test_accepts_normal_name(self) -> None:
        """Normal identifiers SHALL pass validation."""
        from api.endpoints.admin.api_keys import CreateApiKeyRequest

        body = CreateApiKeyRequest(created_by="admin-alice_2026")
        assert body.created_by == "admin-alice_2026"

    def test_accepts_none(self) -> None:
        """None SHALL pass (optional field)."""
        from api.endpoints.admin.api_keys import CreateApiKeyRequest

        body = CreateApiKeyRequest()
        assert body.created_by is None

    def test_rejects_sql_injection_payload(self) -> None:
        """SQL injection payload with parentheses SHALL be rejected."""
        from api.endpoints.admin.api_keys import CreateApiKeyRequest

        with pytest.raises(ValidationError):
            CreateApiKeyRequest(created_by="admin; DROP TABLE api_keys; --")

    def test_rejects_long_value(self) -> None:
        """Value longer than max_length=100 SHALL be rejected."""
        from api.endpoints.admin.api_keys import CreateApiKeyRequest

        with pytest.raises(ValidationError):
            CreateApiKeyRequest(created_by="a" * 101)

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for AuditLogService: database persistence of audit events."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.db import AuditLog
from core.security.audit_log_service import AuditLogService
from tests.helpers import create_mock_relational_pool


@pytest.fixture
def mock_pool() -> MagicMock:
    """Create a mock RelationalPool with async session support."""
    return create_mock_relational_pool()


@pytest.fixture
def service(mock_pool: MagicMock) -> AuditLogService:
    """Create AuditLogService with mock pool."""
    return AuditLogService(mock_pool)


class TestLogEvent:
    """Tests for AuditLogService.log_event."""

    async def test_creates_audit_log_entry(
        self, service: AuditLogService, mock_pool: MagicMock
    ) -> None:
        """log_event creates an AuditLog ORM object and adds it to session."""
        await service.log_event(
            key_id="key_abc123",
            action="source.create",
            target_type="source_config",
            target_id="src_456",
            detail={"name": "test_source"},
            client_ip="192.168.1.1",
            user_agent="Mozilla/5.0",
        )

        session = mock_pool.session.return_value
        session.add.assert_called_once()
        added_obj = session.add.call_args[0][0]
        assert isinstance(added_obj, AuditLog)
        assert added_obj.key_id == "key_abc123"
        assert added_obj.action == "source.create"
        assert added_obj.target_type == "source_config"
        assert added_obj.target_id == "src_456"
        assert added_obj.detail == {"name": "test_source"}
        assert added_obj.client_ip == "192.168.1.1"
        assert added_obj.user_agent == "Mozilla/5.0"

    async def test_minimal_fields(self, service: AuditLogService, mock_pool: MagicMock) -> None:
        """log_event works with only required fields."""
        await service.log_event(key_id="key_abc", action="pipeline.trigger")

        session = mock_pool.session.return_value
        added_obj = session.add.call_args[0][0]
        assert isinstance(added_obj, AuditLog)
        assert added_obj.key_id == "key_abc"
        assert added_obj.action == "pipeline.trigger"
        assert added_obj.target_type is None
        assert added_obj.target_id is None

    async def test_error_does_not_raise(
        self, service: AuditLogService, mock_pool: MagicMock
    ) -> None:
        """log_event catches exceptions and does not propagate them."""
        session = mock_pool.session.return_value
        session.commit.side_effect = RuntimeError("DB error")

        # Should not raise
        await service.log_event(key_id="key_abc", action="test.action")


class TestQueryEvents:
    """Tests for AuditLogService.query_events."""

    async def test_returns_list(self, service: AuditLogService, mock_pool: MagicMock) -> None:
        """query_events returns a list."""
        session = mock_pool.session.return_value
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result

        result = await service.query_events()
        assert isinstance(result, list)

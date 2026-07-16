# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for services protocol definitions."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.protocols.services import (
    PipelineService,
    TaskRegistryService,
)


class TestPipelineServiceProtocol:
    """Test PipelineService protocol."""

    def test_protocol_is_runtime_checkable(self):
        """Test that PipelineService is runtime checkable."""
        from typing import runtime_checkable

        assert runtime_checkable

    def test_protocol_has_required_methods(self):
        """Test that PipelineService defines required methods."""
        # Check protocol has the expected methods
        assert hasattr(PipelineService, "run_phase3_per_article")
        assert hasattr(PipelineService, "get_pipeline_status")
        assert hasattr(PipelineService, "run_full_pipeline")

    def test_mock_implementation_satisfies_protocol(self):
        """Test that a mock implementation satisfies the protocol."""
        mock_service = MagicMock(spec=PipelineService)
        mock_service.run_phase3_per_article = AsyncMock()
        mock_service.get_pipeline_status = AsyncMock()
        mock_service.run_full_pipeline = AsyncMock()

        assert isinstance(mock_service, PipelineService)


class TestTaskRegistryServiceProtocol:
    """Test TaskRegistryService protocol."""

    def test_protocol_has_required_methods(self):
        """Test that TaskRegistryService defines required methods."""
        assert hasattr(TaskRegistryService, "register")
        assert hasattr(TaskRegistryService, "get_status")
        assert hasattr(TaskRegistryService, "cancel")
        assert hasattr(TaskRegistryService, "list_tasks")

    def test_mock_implementation_satisfies_protocol(self):
        """Test that a mock implementation satisfies the protocol."""
        mock_service = MagicMock(spec=TaskRegistryService)
        mock_service.register = AsyncMock()
        mock_service.get_status = AsyncMock()
        mock_service.cancel = AsyncMock()
        mock_service.list_tasks = AsyncMock()

        assert isinstance(mock_service, TaskRegistryService)


class TestServiceProtocolIntegration:
    """Test service protocols can be used for type checking."""

    @pytest.mark.asyncio
    async def test_pipeline_service_mock_usage(self):
        """Test using PipelineService mock."""
        mock_service = MagicMock(spec=PipelineService)
        mock_service.run_phase3_per_article.return_value = {
            "article_id": "123",
            "status": "success",
        }

        result = await mock_service.run_phase3_per_article("123")
        assert result["article_id"] == "123"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_task_registry_service_mock_usage(self):
        """Test using TaskRegistryService mock."""
        mock_service = MagicMock(spec=TaskRegistryService)
        mock_service.get_status.return_value = {
            "status": "running",
            "progress": 0.5,
        }

        result = await mock_service.get_status("task-123")
        assert result["status"] == "running"
        assert result["progress"] == 0.5

    def test_protocols_are_in_all(self):
        """Test that protocols are exported in __all__."""
        from core.protocols import services

        assert "PipelineService" in services.__all__
        assert "TaskRegistryService" in services.__all__

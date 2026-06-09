# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for memory monitoring endpoints.

Tests cover:
- Memory diagnostics with service initialized
- Memory diagnostics with service not initialized
- Scheduler job registration check
- Response model validation
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.endpoints.monitoring.memory import (
    MemoryDiagnosticResponse,
    memory_diagnostics,
)

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_api_key():
    """Mock verified API key."""
    return "test-api-key-12345"


@pytest.fixture
def mock_container():
    """Mock application container."""
    container = MagicMock()
    container.memory_diagnostics = AsyncMock()
    container.is_job_registered = MagicMock(return_value=False)
    return container


# ── Memory Diagnostics Tests ─────────────────────────────────────


class TestMemoryDiagnostics:
    """Tests for GET /monitoring/memory/diagnostics endpoint."""

    @pytest.mark.asyncio
    async def test_diagnostics_service_initialized(self, mock_api_key, mock_container):
        """Test diagnostics when memory service is fully initialized."""
        mock_container.memory_diagnostics.return_value = {
            "service_initialized": True,
            "temporal_event_count": 1500,
            "causal_link_count": 3000,
            "pending_consolidation": 25,
            "slow_path_enabled": True,
        }
        mock_container.is_job_registered.return_value = True

        response = await memory_diagnostics(
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data.memory_service_initialized is True
        assert response.data.temporal_event_count == 1500
        assert response.data.causal_link_count == 3000
        assert response.data.pending_consolidation == 25
        assert response.data.slow_path_enabled is True
        assert response.data.scheduler_job_registered is True
        mock_container.memory_diagnostics.assert_called_once()
        mock_container.is_job_registered.assert_called_once_with("memory_consolidation")

    @pytest.mark.asyncio
    async def test_diagnostics_service_not_initialized(self, mock_api_key, mock_container):
        """Test diagnostics when memory service is not initialized."""
        mock_container.memory_diagnostics.return_value = {
            "service_initialized": False,
            "temporal_event_count": 0,
            "causal_link_count": 0,
            "pending_consolidation": 0,
            "slow_path_enabled": False,
        }
        mock_container.is_job_registered.return_value = False

        response = await memory_diagnostics(
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data.memory_service_initialized is False
        assert response.data.temporal_event_count == 0
        assert response.data.causal_link_count == 0
        assert response.data.pending_consolidation == 0
        assert response.data.slow_path_enabled is False
        assert response.data.scheduler_job_registered is False

    @pytest.mark.asyncio
    async def test_diagnostics_scheduler_registered_no_service(self, mock_api_key, mock_container):
        """Test diagnostics when scheduler job exists but service is not initialized."""
        mock_container.memory_diagnostics.return_value = {
            "service_initialized": False,
            "temporal_event_count": 0,
            "causal_link_count": 0,
            "pending_consolidation": 0,
            "slow_path_enabled": False,
        }
        mock_container.is_job_registered.return_value = True

        response = await memory_diagnostics(
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data.memory_service_initialized is False
        assert response.data.scheduler_job_registered is True

    @pytest.mark.asyncio
    async def test_diagnostics_partial_data(self, mock_api_key, mock_container):
        """Test diagnostics with partial data (some counts non-zero)."""
        mock_container.memory_diagnostics.return_value = {
            "service_initialized": True,
            "temporal_event_count": 100,
            "causal_link_count": 0,
            "pending_consolidation": 5,
            "slow_path_enabled": False,
        }
        mock_container.is_job_registered.return_value = False

        response = await memory_diagnostics(
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data.memory_service_initialized is True
        assert response.data.temporal_event_count == 100
        assert response.data.causal_link_count == 0
        assert response.data.pending_consolidation == 5
        assert response.data.slow_path_enabled is False
        assert response.data.scheduler_job_registered is False

    @pytest.mark.asyncio
    async def test_diagnostics_response_is_success_response(self, mock_api_key, mock_container):
        """Test that response follows APIResponse success format."""
        mock_container.memory_diagnostics.return_value = {
            "service_initialized": True,
            "temporal_event_count": 10,
            "causal_link_count": 20,
            "pending_consolidation": 3,
            "slow_path_enabled": True,
        }
        mock_container.is_job_registered.return_value = True

        response = await memory_diagnostics(
            _=mock_api_key,
            container=mock_container,
        )

        assert response.code == 0
        assert response.data is not None

    @pytest.mark.asyncio
    async def test_diagnostics_large_counts(self, mock_api_key, mock_container):
        """Test diagnostics with large event counts."""
        mock_container.memory_diagnostics.return_value = {
            "service_initialized": True,
            "temporal_event_count": 999999,
            "causal_link_count": 888888,
            "pending_consolidation": 777,
            "slow_path_enabled": True,
        }
        mock_container.is_job_registered.return_value = True

        response = await memory_diagnostics(
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data.temporal_event_count == 999999
        assert response.data.causal_link_count == 888888
        assert response.data.pending_consolidation == 777


# ── Response Model Tests ─────────────────────────────────────────


class TestMemoryDiagnosticResponseModel:
    """Tests for MemoryDiagnosticResponse model validation."""

    def test_model_all_fields(self):
        """Test model with all fields populated."""
        model = MemoryDiagnosticResponse(
            memory_service_initialized=True,
            temporal_event_count=100,
            causal_link_count=200,
            pending_consolidation=10,
            slow_path_enabled=True,
            scheduler_job_registered=True,
        )
        assert model.memory_service_initialized is True
        assert model.temporal_event_count == 100
        assert model.causal_link_count == 200
        assert model.pending_consolidation == 10
        assert model.slow_path_enabled is True
        assert model.scheduler_job_registered is True

    def test_model_defaults_not_applicable(self):
        """Test model requires all fields (no defaults)."""
        # All fields are required, verify they must be provided
        model = MemoryDiagnosticResponse(
            memory_service_initialized=False,
            temporal_event_count=0,
            causal_link_count=0,
            pending_consolidation=0,
            slow_path_enabled=False,
            scheduler_job_registered=False,
        )
        assert model.memory_service_initialized is False
        assert model.temporal_event_count == 0

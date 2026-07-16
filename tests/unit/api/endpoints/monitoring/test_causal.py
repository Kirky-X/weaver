# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for causal graph monitoring endpoints.

Tests cover:
- Causal stats with repository available
- Causal stats with repository unavailable (503)
- Causal stats with zero edges
- Causal stats with large edge count
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.endpoints.monitoring.causal import get_causal_stats

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_api_key():
    """Mock verified API key."""
    return "test-api-key-12345"


@pytest.fixture
def mock_container():
    """Mock application container."""
    container = MagicMock()
    container.causal_repo = MagicMock()
    return container


@pytest.fixture
def mock_causal_repo():
    """Mock causal repository."""
    repo = AsyncMock()
    repo.count_causal_links = AsyncMock(return_value=0)
    return repo


# ── Causal Stats Tests ───────────────────────────────────────────


class TestGetCausalStats:
    """Tests for GET /monitoring/causal/stats endpoint."""

    @pytest.mark.asyncio
    async def test_stats_with_causal_edges(self, mock_api_key, mock_container, mock_causal_repo):
        """Test stats when causal graph has edges."""
        mock_causal_repo.count_causal_links.return_value = 42
        mock_container.causal_repo.return_value = mock_causal_repo

        response = await get_causal_stats(
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data["causal_edges"] == 42
        assert response.data["edge_types"] == ["CAUSES", "ENABLES", "PREVENTS"]
        mock_causal_repo.count_causal_links.assert_called_once()

    @pytest.mark.asyncio
    async def test_stats_no_edges(self, mock_api_key, mock_container, mock_causal_repo):
        """Test stats when causal graph has no edges."""
        mock_causal_repo.count_causal_links.return_value = 0
        mock_container.causal_repo.return_value = mock_causal_repo

        response = await get_causal_stats(
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data["causal_edges"] == 0
        assert response.data["edge_types"] == ["CAUSES", "ENABLES", "PREVENTS"]

    @pytest.mark.asyncio
    async def test_stats_repo_unavailable(self, mock_api_key, mock_container):
        """Test stats raises 503 when causal repo is unavailable."""
        mock_container.causal_repo.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_causal_stats(
                _=mock_api_key,
                container=mock_container,
            )

        assert exc_info.value.status_code == 503
        assert "Causal graph repository unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_stats_response_is_success_format(
        self, mock_api_key, mock_container, mock_causal_repo
    ):
        """Test that response follows APIResponse success format."""
        mock_causal_repo.count_causal_links.return_value = 10
        mock_container.causal_repo.return_value = mock_causal_repo

        response = await get_causal_stats(
            _=mock_api_key,
            container=mock_container,
        )

        assert response.code == 0
        assert response.data is not None

    @pytest.mark.asyncio
    async def test_stats_large_edge_count(self, mock_api_key, mock_container, mock_causal_repo):
        """Test stats with large number of causal edges."""
        mock_causal_repo.count_causal_links.return_value = 999999
        mock_container.causal_repo.return_value = mock_causal_repo

        response = await get_causal_stats(
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data["causal_edges"] == 999999

    @pytest.mark.asyncio
    async def test_stats_edge_types_always_present(
        self, mock_api_key, mock_container, mock_causal_repo
    ):
        """Test that edge_types list is always returned regardless of count."""
        mock_causal_repo.count_causal_links.return_value = 0
        mock_container.causal_repo.return_value = mock_causal_repo

        response = await get_causal_stats(
            _=mock_api_key,
            container=mock_container,
        )

        assert "edge_types" in response.data
        assert len(response.data["edge_types"]) == 3
        assert "CAUSES" in response.data["edge_types"]
        assert "ENABLES" in response.data["edge_types"]
        assert "PREVENTS" in response.data["edge_types"]

    @pytest.mark.asyncio
    async def test_stats_container_causal_repo_called(
        self, mock_api_key, mock_container, mock_causal_repo
    ):
        """Test that container.causal_repo() is called to obtain the repo."""
        mock_container.causal_repo.return_value = mock_causal_repo

        await get_causal_stats(
            _=mock_api_key,
            container=mock_container,
        )

        mock_container.causal_repo.assert_called_once()

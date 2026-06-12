# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.migration.adapters.ladybug_target module."""

from unittest.mock import AsyncMock, patch

import pytest

from modules.migration.adapters.ladybug_target import LadybugTarget
from modules.migration.exceptions import ValidationFailedError
from modules.migration.models import ColumnDef, NodeSchema, RelSchema


class TestLadybugTargetInit:
    """Test LadybugTarget initialization."""

    def test_init(self, graph_mock_pool):
        """Test initialization."""
        target = LadybugTarget(graph_mock_pool)

        assert target._pool is graph_mock_pool


class TestLadybugTargetEnsureNodeSchema:
    """Test ensure_node_schema method."""

    @pytest.fixture
    def target(self, graph_mock_pool):
        """Create LadybugTarget with mock pool."""
        return LadybugTarget(graph_mock_pool)

    @pytest.mark.asyncio
    async def test_ensure_node_schema_creates_indexes(self, target):
        """Test ensure_node_schema creates indexes."""
        schemas = [
            NodeSchema(
                label="Entity",
                primary_key="id",
                properties=[ColumnDef(name="id", data_type="STRING", nullable=False)],
            ),
        ]

        target._pool.execute_query = AsyncMock()

        await target.ensure_node_schema(schemas)

        # Should have called execute_query for indexes
        assert target._pool.execute_query.called


class TestLadybugTargetEnsureRelSchema:
    """Test ensure_rel_schema method."""

    @pytest.fixture
    def target(self, graph_mock_pool):
        """Create LadybugTarget with mock pool."""
        return LadybugTarget(graph_mock_pool)

    @pytest.mark.asyncio
    async def test_ensure_rel_schema_creates_indexes(self, target):
        """Test ensure_rel_schema creates indexes."""
        schemas = [
            RelSchema(
                type="RELATED_TO",
                source_label="Entity",
                target_label="Entity",
            ),
        ]

        target._pool.execute_query = AsyncMock()

        await target.ensure_rel_schema(schemas)

        # Should have called execute_query for indexes
        assert target._pool.execute_query.called


class TestLadybugTargetWriteNodes:
    """Test write_nodes method."""

    @pytest.fixture
    def target(self, graph_mock_pool):
        """Create LadybugTarget with mock pool."""
        return LadybugTarget(graph_mock_pool)

    @pytest.mark.asyncio
    async def test_write_nodes_empty(self, target):
        """Test write_nodes with empty list."""
        count = await target.write_nodes("Entity", [])

        assert count == 0

    @pytest.mark.asyncio
    async def test_write_nodes_inserts_nodes(self, target):
        """Test write_nodes inserts nodes."""
        nodes = [
            {"id": "1", "name": "Entity1"},
            {"id": "2", "name": "Entity2"},
        ]

        target._pool.execute_query = AsyncMock()

        count = await target.write_nodes("Entity", nodes)

        # Each node should trigger a query
        assert count == 2


class TestLadybugTargetWriteRels:
    """Test write_rels method."""

    @pytest.fixture
    def target(self, graph_mock_pool):
        """Create LadybugTarget with mock pool."""
        return LadybugTarget(graph_mock_pool)

    @pytest.mark.asyncio
    async def test_write_rels_empty(self, target):
        """Test write_rels with empty list."""
        count = await target.write_rels("RELATED_TO", [])

        assert count == 0

    @pytest.mark.asyncio
    async def test_write_rels_inserts_rels(self, target):
        """Test write_rels inserts relationships."""
        rels = [
            {
                "_source_id": "1",
                "_target_id": "2",
                "_source_label": "Entity",
                "_target_label": "Entity",
            },
        ]

        target._pool.execute_query = AsyncMock()

        count = await target.write_rels("RELATED_TO", rels)

        assert count == 1


class TestLadybugTargetVerifyNodes:
    """Test verify_nodes method."""

    @pytest.fixture
    def target(self, graph_mock_pool):
        """Create LadybugTarget with mock pool."""
        return LadybugTarget(graph_mock_pool)

    @pytest.mark.asyncio
    async def test_verify_nodes_success(self, target):
        """Test verify_nodes succeeds when count matches."""
        target._pool.execute_query = AsyncMock(return_value=[{"count": 100}])

        result = await target.verify_nodes("Entity", 100)

        assert result is True

    @pytest.mark.asyncio
    async def test_verify_nodes_fails_on_mismatch(self, target):
        """Test verify_nodes fails when count doesn't match."""
        target._pool.execute_query = AsyncMock(return_value=[{"count": 50}])

        with pytest.raises(ValidationFailedError):
            await target.verify_nodes("Entity", 100)


class TestLadybugTargetVerifyRels:
    """Test verify_rels method."""

    @pytest.fixture
    def target(self, graph_mock_pool):
        """Create LadybugTarget with mock pool."""
        return LadybugTarget(graph_mock_pool)

    @pytest.mark.asyncio
    async def test_verify_rels_success(self, target):
        """Test verify_rels succeeds when count matches."""
        target._pool.execute_query = AsyncMock(return_value=[{"count": 100}])

        result = await target.verify_rels("RELATED_TO", 100)

        assert result is True

    @pytest.mark.asyncio
    async def test_verify_rels_fails_on_mismatch(self, target):
        """Test verify_rels fails when count doesn't match."""
        target._pool.execute_query = AsyncMock(return_value=[{"count": 50}])

        with pytest.raises(ValidationFailedError):
            await target.verify_rels("RELATED_TO", 100)


class TestLadybugTargetClearLabel:
    """Test clear_label method."""

    @pytest.fixture
    def target(self, graph_mock_pool):
        """Create LadybugTarget with mock pool."""
        return LadybugTarget(graph_mock_pool)

    @pytest.mark.asyncio
    async def test_clear_label(self, target):
        """Test clear_label executes."""
        target._pool.execute_query = AsyncMock()

        await target.clear_label("Entity")

        assert target._pool.execute_query.called

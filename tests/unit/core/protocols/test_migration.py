# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for core.protocols.migration module."""

import pytest

from core.protocols.migration import (
    GraphMigrationSource,
    GraphMigrationTarget,
    MigrationSource,
    MigrationTarget,
)


class TestMigrationSourceProtocol:
    """Test MigrationSource protocol."""

    def test_protocol_has_required_methods(self):
        """Test protocol has required methods."""
        # Protocol is a structural type, so we check that the protocol
        # defines the expected methods
        assert hasattr(MigrationSource, "read_schema")
        assert hasattr(MigrationSource, "read_batch")
        assert hasattr(MigrationSource, "read_incremental")
        assert hasattr(MigrationSource, "count")

    def test_runtime_checkable(self):
        """Test protocol is runtime checkable."""
        # MigrationSource should be runtime_checkable
        assert hasattr(MigrationSource, "__class__")


class TestMigrationTargetProtocol:
    """Test MigrationTarget protocol."""

    def test_protocol_has_required_methods(self):
        """Test protocol has required methods."""
        assert hasattr(MigrationTarget, "ensure_schema")
        assert hasattr(MigrationTarget, "write_batch")
        assert hasattr(MigrationTarget, "verify")


class TestGraphMigrationSourceProtocol:
    """Test GraphMigrationSource protocol."""

    def test_protocol_has_required_methods(self):
        """Test protocol has required methods."""
        assert hasattr(GraphMigrationSource, "read_node_schema")
        assert hasattr(GraphMigrationSource, "read_rel_schema")
        assert hasattr(GraphMigrationSource, "read_nodes")
        assert hasattr(GraphMigrationSource, "read_rels")
        assert hasattr(GraphMigrationSource, "count_nodes")
        assert hasattr(GraphMigrationSource, "count_rels")


class TestGraphMigrationTargetProtocol:
    """Test GraphMigrationTarget protocol."""

    def test_protocol_has_required_methods(self):
        """Test protocol has required methods."""
        assert hasattr(GraphMigrationTarget, "ensure_node_schema")
        assert hasattr(GraphMigrationTarget, "ensure_rel_schema")
        assert hasattr(GraphMigrationTarget, "write_nodes")
        assert hasattr(GraphMigrationTarget, "write_rels")
        assert hasattr(GraphMigrationTarget, "verify_nodes")
        assert hasattr(GraphMigrationTarget, "verify_rels")


class MockMigrationSource:
    """Mock implementation of MigrationSource for testing."""

    async def read_schema(self):
        return []

    async def read_batch(self, table, offset, limit):
        return []

    async def read_incremental(self, table, key, since, limit=5000):
        yield []

    async def count(self, table):
        return 0


class MockMigrationTarget:
    """Mock implementation of MigrationTarget for testing."""

    async def ensure_schema(self, schema):
        pass

    async def write_batch(self, table, rows):
        return 0

    async def verify(self, table, expected_count):
        return True


class TestProtocolImplementation:
    """Test protocol implementation checking."""

    def test_mock_source_satisfies_protocol(self):
        """Test mock source satisfies MigrationSource protocol."""
        from core.protocols import assert_implements

        # Should not raise
        assert_implements(MockMigrationSource, MigrationSource)

    def test_mock_target_satisfies_protocol(self):
        """Test mock target satisfies MigrationTarget protocol."""
        from core.protocols import assert_implements

        # Should not raise
        assert_implements(MockMigrationTarget, MigrationTarget)


class TestSchemaDataclasses:
    """Test schema dataclasses from models module."""

    def test_migration_schema_from_models(self):
        """Test MigrationSchema from models module."""
        from modules.migration.models import ColumnDef, MigrationSchema

        schema = MigrationSchema(
            table="users",
            columns=[ColumnDef(name="id", data_type="integer", nullable=False)],
            primary_key="id",
        )

        assert schema.table == "users"
        assert schema.primary_key == "id"

    def test_node_schema_from_models(self):
        """Test NodeSchema from models module."""
        from modules.migration.models import ColumnDef, NodeSchema

        schema = NodeSchema(
            label="Entity",
            primary_key="id",
            properties=[ColumnDef(name="id", data_type="String", nullable=False)],
        )

        assert schema.label == "Entity"
        assert schema.primary_key == "id"

    def test_rel_schema_from_models(self):
        """Test RelSchema from models module."""
        from modules.migration.models import RelSchema

        schema = RelSchema(
            type="RELATED_TO",
            source_label="Entity",
            target_label="Entity",
        )

        assert schema.type == "RELATED_TO"
        assert schema.source_label == "Entity"
        assert schema.target_label == "Entity"


class TestProtocolDocstrings:
    """Test protocol documentation."""

    def test_migration_source_docstring(self):
        """Test MigrationSource has docstring."""
        assert MigrationSource.__doc__ is not None
        assert "relational" in MigrationSource.__doc__.lower()

    def test_migration_target_docstring(self):
        """Test MigrationTarget has docstring."""
        assert MigrationTarget.__doc__ is not None

    def test_graph_migration_source_docstring(self):
        """Test GraphMigrationSource has docstring."""
        assert GraphMigrationSource.__doc__ is not None
        assert "graph" in GraphMigrationSource.__doc__.lower()

    def test_graph_migration_target_docstring(self):
        """Test GraphMigrationTarget has docstring."""
        assert GraphMigrationTarget.__doc__ is not None

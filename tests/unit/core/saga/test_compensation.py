# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for Saga compensation command models."""

from __future__ import annotations

import pytest

from core.saga.compensation import (
    CompensationCommand,
    Neo4jCompensation,
    PostgresCompensation,
    deserialize_compensation,
)


class TestPostgresCompensation:
    """Tests for PostgresCompensation command."""

    def test_create_insert_compensation(self):
        cmd = PostgresCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="pg_insert",
            operation="insert",
        )
        assert cmd.saga_id == "saga-1"
        assert cmd.operation == "insert"
        assert cmd.backup_data is None

    def test_create_update_compensation_with_backup(self):
        backup = {"title": "Original Title", "category": "科技"}
        cmd = PostgresCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="pg_update",
            operation="update",
            backup_data=backup,
        )
        assert cmd.backup_data == backup

    def test_serialize_insert(self):
        cmd = PostgresCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="pg_insert",
            operation="insert",
        )
        data = cmd.serialize()
        assert data["type"] == "postgres"
        assert data["saga_id"] == "saga-1"
        assert data["operation"] == "insert"
        assert data["backup_data"] is None

    def test_serialize_update_with_backup(self):
        cmd = PostgresCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="pg_update",
            operation="update",
            backup_data={"title": "Old"},
        )
        data = cmd.serialize()
        assert data["backup_data"] == {"title": "Old"}

    def test_deserialize_insert(self):
        data = {
            "type": "postgres",
            "saga_id": "saga-1",
            "article_id": "art-1",
            "step_name": "pg_insert",
            "operation": "insert",
            "backup_data": None,
        }
        cmd = PostgresCompensation.deserialize(data)
        assert isinstance(cmd, PostgresCompensation)
        assert cmd.saga_id == "saga-1"
        assert cmd.operation == "insert"

    def test_roundtrip_serialize_deserialize(self):
        original = PostgresCompensation(
            saga_id="saga-2",
            article_id="art-2",
            step_name="pg_status_change",
            operation="status_change",
            backup_data={"old_status": "pending"},
        )
        data = original.serialize()
        restored = PostgresCompensation.deserialize(data)
        assert restored.saga_id == original.saga_id
        assert restored.article_id == original.article_id
        assert restored.operation == original.operation
        assert restored.backup_data == original.backup_data

    @pytest.mark.asyncio
    async def test_execute_does_not_raise(self):
        """Execute should not raise — actual DB ops delegated to executor."""
        cmd = PostgresCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="pg_insert",
            operation="insert",
        )
        await cmd.execute()  # Should not raise


class TestNeo4jCompensation:
    """Tests for Neo4jCompensation command."""

    def test_create_entity_create_compensation(self):
        cmd = Neo4jCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="neo4j_entity",
            operation="entity_create",
            entity_ids=["e1", "e2"],
        )
        assert cmd.entity_ids == ["e1", "e2"]
        assert cmd.relationship_ids == []

    def test_create_relationship_create_compensation(self):
        cmd = Neo4jCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="neo4j_rel",
            operation="relationship_create",
            relationship_ids=["r1"],
        )
        assert cmd.relationship_ids == ["r1"]

    def test_serialize_entity_create(self):
        cmd = Neo4jCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="neo4j_entity",
            operation="entity_create",
            entity_ids=["e1"],
        )
        data = cmd.serialize()
        assert data["type"] == "neo4j"
        assert data["entity_ids"] == ["e1"]

    def test_deserialize(self):
        data = {
            "type": "neo4j",
            "saga_id": "saga-1",
            "article_id": "art-1",
            "step_name": "neo4j_entity",
            "operation": "entity_create",
            "entity_ids": ["e1", "e2"],
            "relationship_ids": [],
        }
        cmd = Neo4jCompensation.deserialize(data)
        assert isinstance(cmd, Neo4jCompensation)
        assert cmd.entity_ids == ["e1", "e2"]

    def test_roundtrip_serialize_deserialize(self):
        original = Neo4jCompensation(
            saga_id="saga-3",
            article_id="art-3",
            step_name="neo4j_community",
            operation="community_assign",
            entity_ids=["e1"],
            relationship_ids=["r1", "r2"],
        )
        data = original.serialize()
        restored = Neo4jCompensation.deserialize(data)
        assert restored.saga_id == original.saga_id
        assert restored.entity_ids == original.entity_ids
        assert restored.relationship_ids == original.relationship_ids

    @pytest.mark.asyncio
    async def test_execute_does_not_raise(self):
        cmd = Neo4jCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="neo4j_entity",
            operation="entity_create",
            entity_ids=["e1"],
        )
        await cmd.execute()


class TestDeserializeCompensation:
    """Tests for the deserialize_compensation factory function."""

    def test_deserialize_postgres(self):
        data = {
            "type": "postgres",
            "saga_id": "saga-1",
            "article_id": "art-1",
            "step_name": "pg_insert",
            "operation": "insert",
        }
        cmd = deserialize_compensation(data)
        assert isinstance(cmd, PostgresCompensation)

    def test_deserialize_neo4j(self):
        data = {
            "type": "neo4j",
            "saga_id": "saga-1",
            "article_id": "art-1",
            "step_name": "neo4j_entity",
            "operation": "entity_create",
            "entity_ids": [],
            "relationship_ids": [],
        }
        cmd = deserialize_compensation(data)
        assert isinstance(cmd, Neo4jCompensation)

    def test_deserialize_unknown_type_raises(self):
        data = {"type": "unknown", "saga_id": "saga-1"}
        with pytest.raises(ValueError, match="Unknown compensation type"):
            deserialize_compensation(data)

    def test_deserialize_missing_type_raises(self):
        data = {"saga_id": "saga-1"}
        with pytest.raises(ValueError, match="Unknown compensation type"):
            deserialize_compensation(data)

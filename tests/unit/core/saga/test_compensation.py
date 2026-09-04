# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for Saga compensation command models."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.db import PersistStatus
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
    async def test_execute_insert_marks_failed_and_cleans_vectors(self):
        """Execute with insert operation should mark articles failed and clean vectors."""
        aid1, aid2 = uuid.uuid4(), uuid.uuid4()
        vid1 = uuid.uuid4()
        cmd = PostgresCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="pg_insert",
            operation="insert",
            article_ids=[str(aid1), str(aid2)],
            vector_article_ids=[str(vid1)],
        )
        mock_article_repo = AsyncMock()
        mock_vector_repo = AsyncMock()
        mock_vector_repo.delete_article_vectors_by_article_ids = AsyncMock(return_value=1)
        cmd.inject_pools(
            article_repo=mock_article_repo,
            vector_repo=mock_vector_repo,
        )

        await cmd.execute()

        assert mock_article_repo.mark_failed.call_count == 2
        mock_vector_repo.delete_article_vectors_by_article_ids.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_status_change_updates_status(self):
        """Execute with status_change should update persist status to FAILED."""
        aid1 = uuid.uuid4()
        cmd = PostgresCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="pg_status",
            operation="status_change",
            article_ids=[str(aid1)],
        )
        mock_article_repo = AsyncMock()
        cmd.inject_pools(article_repo=mock_article_repo)

        await cmd.execute()

        mock_article_repo.update_persist_status.assert_called_once_with(
            aid1,
            PersistStatus.FAILED,
        )

    @pytest.mark.asyncio
    async def test_execute_without_pools_is_safe_noop(self):
        """Execute without injected pools should not raise."""
        cmd = PostgresCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="pg_insert",
            operation="insert",
            article_ids=["some-id"],
        )
        await cmd.execute()  # No pools → no-op, should not raise

    def test_serialize_includes_batch_fields(self):
        cmd = PostgresCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="pg_insert",
            operation="insert",
            article_ids=["a1", "a2"],
            vector_article_ids=["v1"],
        )
        data = cmd.serialize()
        assert data["article_ids"] == ["a1", "a2"]
        assert data["vector_article_ids"] == ["v1"]

    def test_serialize_converts_uuid_to_str(self):
        aid = uuid.uuid4()
        cmd = PostgresCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="pg_insert",
            operation="insert",
            article_ids=[aid],
        )
        data = cmd.serialize()
        assert data["article_ids"] == [str(aid)]

    def test_deserialize_backward_compatible(self):
        """Deserialize old format without article_ids should default to empty lists."""
        data = {
            "type": "postgres",
            "saga_id": "saga-1",
            "article_id": "art-1",
            "step_name": "pg_insert",
            "operation": "insert",
        }
        cmd = PostgresCompensation.deserialize(data)
        assert cmd.article_ids == []
        assert cmd.vector_article_ids == []


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
    async def test_execute_marks_articles_failed_with_pools(self):
        """Execute should mark article_ids as FAILED when pools are injected."""
        aid1 = uuid.uuid4()
        cmd = Neo4jCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="neo4j_entity",
            operation="entity_create",
            entity_ids=["e1"],
            article_ids=[str(aid1)],
        )
        mock_article_repo = AsyncMock()
        cmd.inject_pools(article_repo=mock_article_repo)

        await cmd.execute()

        mock_article_repo.update_persist_status.assert_called_once_with(
            aid1,
            PersistStatus.FAILED,
        )

    @pytest.mark.asyncio
    async def test_execute_without_pools_is_safe_noop(self):
        cmd = Neo4jCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="neo4j_entity",
            operation="entity_create",
            entity_ids=["e1"],
            article_ids=["some-id"],
        )
        await cmd.execute()  # No pools → no-op

    def test_serialize_includes_article_ids(self):
        cmd = Neo4jCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="neo4j_entity",
            operation="entity_create",
            entity_ids=["e1"],
            article_ids=["a1", "a2"],
        )
        data = cmd.serialize()
        assert data["article_ids"] == ["a1", "a2"]

    def test_deserialize_backward_compatible(self):
        """Deserialize old format without article_ids should default to empty list."""
        data = {
            "type": "neo4j",
            "saga_id": "saga-1",
            "article_id": "art-1",
            "step_name": "neo4j_entity",
            "operation": "entity_create",
            "entity_ids": [],
            "relationship_ids": [],
        }
        cmd = Neo4jCompensation.deserialize(data)
        assert cmd.article_ids == []


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


class TestBatchMergerCompensationDataFormat:
    """Regression tests: compensation data from batch_merger must deserialize.

    The orchestrated saga path in batch_merger builds compensation_data dicts
    with batch-level fields (article_ids list) and no single article_id.
    These must deserialize without KeyError.
    """

    def test_postgres_batch_compensation_data_deserializes(self):
        """pg_compensation_data from _run_orchestrated_saga must deserialize."""
        # This is the exact format batch_merger produces
        batch_comp_data = {
            "type": "postgres",
            "step_name": "persist_postgresql",
            "operation": "insert",
            "saga_id": "",
            "article_id": "",
            "article_ids": [],
            "vector_article_ids": [],
        }
        cmd = deserialize_compensation(batch_comp_data)
        assert isinstance(cmd, PostgresCompensation)
        assert cmd.article_ids == []
        assert cmd.vector_article_ids == []

    def test_neo4j_batch_compensation_data_deserializes(self):
        """neo4j_compensation_data from _run_orchestrated_saga must deserialize."""
        batch_comp_data = {
            "type": "neo4j",
            "step_name": "persist_neo4j",
            "operation": "entity_create",
            "saga_id": "",
            "article_id": "",
            "article_ids": [],
        }
        cmd = deserialize_compensation(batch_comp_data)
        assert isinstance(cmd, Neo4jCompensation)
        assert cmd.article_ids == []

    def test_postgres_batch_compensation_without_article_id_still_works(self):
        """Defense-in-depth: even without article_id, deserialize should not crash."""
        batch_comp_data = {
            "type": "postgres",
            "step_name": "persist_postgresql",
            "operation": "insert",
            "saga_id": "",
            "article_ids": ["a1"],
            "vector_article_ids": ["v1"],
        }
        cmd = deserialize_compensation(batch_comp_data)
        assert isinstance(cmd, PostgresCompensation)
        assert cmd.article_id == ""
        assert cmd.article_ids == ["a1"]

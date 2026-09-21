# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""LOW remediation behaviour tests: modules/storage batch."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.graph_readers.article import GraphArticleReader
from modules.storage.graph_readers.visualizer import GraphVisualizer


def _reader(reader_cls, rows):
    """Build a graph reader whose execute_fn yields pre-canned rows."""
    reader = reader_cls(pool=MagicMock(), query_builder=MagicMock(), execute_fn=AsyncMock())
    reader._execute_fn = AsyncMock(return_value=rows)
    return reader


class TestArticleRelationshipsNullSafety:
    """#274: NULL source/target names normalize like get_article_entities."""

    @pytest.mark.asyncio
    async def test_null_source_target_become_empty_strings(self):
        reader = _reader(
            GraphArticleReader,
            [{"source": None, "target": None, "relation_type": None}],
        )

        rels = await reader.get_article_relationships("article-1")

        assert rels[0]["source_id"] == ""
        assert rels[0]["target_id"] == ""
        assert rels[0]["relation_type"] == "RELATED_TO"


class TestVisualizerEdgeWeightDefault:
    """#276: missing/NULL edge weight falls back to 0 like other fields."""

    @pytest.mark.asyncio
    async def test_null_weight_becomes_zero(self):
        reader = _reader(
            GraphVisualizer,
            [{"source": "a", "target": "b", "relation_type": "RELATED_TO", "weight": None}],
        )

        edges = await reader.get_visualization_edges(["n1"])

        assert edges[0]["weight"] == 0


class TestNeo4jFollowedByCountIntCast:
    """#279: count() results are wrapped in int() like sibling methods."""

    @pytest.mark.asyncio
    async def test_create_followed_by_batch_returns_int(self):
        from modules.storage.neo4j.article_repo import Neo4jArticleRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"created": 7}])
        repo = Neo4jArticleRepo(pool=pool)

        created = await repo.create_followed_by_batch(
            [{"from_pg_id": "a", "to_pg_id": "b", "time_gap_hours": 3}]
        )

        assert type(created) is int
        assert created == 7


class TestVersionRepoKeepsEmptyChangedFields:
    """#285: changed_fields=[] is stored as [], not silently as NULL."""

    @pytest.mark.asyncio
    async def test_empty_list_is_preserved(self):
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        pool = MagicMock()
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        pool.session = MagicMock(return_value=session)
        repo = ArticleVersionRepo(pool)

        await repo.create_version(
            article_id=uuid.uuid4(),
            title="T",
            body="B",
            summary=None,
            category=None,
            score=None,
            changed_fields=[],
        )

        version = session.add.call_args[0][0]
        assert version.changed_fields == []


class TestPendingSyncMarkFailedMissingRecord:
    """#286: marking a missing pending_sync record skips commit (warning path)."""

    @pytest.mark.asyncio
    async def test_missing_record_skips_commit(self):
        from modules.storage.postgres.pending_sync_repo import PendingSyncRepo

        pool = MagicMock()
        session = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        pool.session = MagicMock(return_value=session)
        repo = PendingSyncRepo(pool)

        await repo.mark_failed(123, "boom")

        # Record missing: no commit, and the no-op is observable via the
        # pending_sync_mark_failed_missing warning.
        session.commit.assert_not_called()
        assert session.execute.await_count == 1

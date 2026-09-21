# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""High-severity fixes verification for memory graph repos.

Covers: Ladybug MERGE edges, hardcoded CAUSES relation types, temporal
append idempotency/orphan retry.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.constants import DatabaseType
from modules.memory.core.graph_types import CausalRelationType
from modules.memory.graphs.causal import CausalGraphRepo
from modules.memory.graphs.temporal import TemporalGraphRepo


def _ladybug_pool():
    pool = MagicMock()
    pool.database_type = DatabaseType.LADYBUG.value
    return pool


# ── Ladybug edge creation is idempotent (MERGE) ────────────


class TestCausalEdgeMerge:
    @pytest.mark.asyncio
    async def test_ladybug_edge_uses_merge(self):
        pool = _ladybug_pool()
        pool.execute_query = AsyncMock(return_value=[{"r": "edge"}])
        repo = CausalGraphRepo(pool)

        await repo._add_causal_edge_ladybug("a", "b", CausalRelationType.CAUSES, 0.9)

        query = pool.execute_query.call_args[0][0]
        assert "MERGE (source)-[r:CAUSES]->(target)" in query
        assert "CREATE (source)" not in query

    @pytest.mark.asyncio
    async def test_neo4j_edge_still_uses_merge(self):
        pool = MagicMock()
        pool.database_type = DatabaseType.NEO4J.value
        pool.execute_query = AsyncMock(return_value=[{"r": "edge"}])
        repo = CausalGraphRepo(pool)

        await repo.add_causal_edge("a", "b", CausalRelationType.CAUSES, 0.9)

        query = pool.execute_query.call_args[0][0]
        assert "MERGE" in query


# ── get_causes/get_effects return real relation types ──────


class TestCausalRelationTypeReturned:
    @pytest.mark.asyncio
    async def test_get_causes_ladybug_queries_each_rel_table(self):
        pool = _ladybug_pool()
        causes_row = {"id": "c1", "relation_type": "CAUSES", "confidence": 0.9}
        enables_row = {"id": "c2", "relation_type": "ENABLES", "confidence": 0.5}
        prevents_row = {"id": "c3", "relation_type": "PREVENTS", "confidence": 0.7}
        pool.execute_query = AsyncMock(side_effect=[[causes_row], [enables_row], [prevents_row]])
        repo = CausalGraphRepo(pool)

        rows = await repo.get_causes("target")

        assert pool.execute_query.await_count == 3
        first_query = pool.execute_query.await_args_list[0][0][0]
        second_query = pool.execute_query.await_args_list[1][0][0]
        third_query = pool.execute_query.await_args_list[2][0][0]
        assert "[r:CAUSES]->" in first_query
        assert "'CAUSES'" in first_query
        assert "[r:ENABLES]->" in second_query
        assert "'ENABLES'" in second_query
        assert "[r:PREVENTS]->" in third_query
        assert "'PREVENTS'" in third_query
        types = {r["relation_type"] for r in rows}
        assert types == {"CAUSES", "ENABLES", "PREVENTS"}

    @pytest.mark.asyncio
    async def test_get_effects_ladybug_queries_each_rel_table(self):
        pool = _ladybug_pool()
        enables_row = {"id": "e1", "relation_type": "ENABLES", "confidence": 0.4}
        pool.execute_query = AsyncMock(side_effect=[[], [enables_row], []])
        repo = CausalGraphRepo(pool)

        rows = await repo.get_effects("source")

        first_query = pool.execute_query.await_args_list[0][0][0]
        second_query = pool.execute_query.await_args_list[1][0][0]
        third_query = pool.execute_query.await_args_list[2][0][0]
        assert "'CAUSES'" in first_query
        assert "'ENABLES'" in second_query
        assert "'PREVENTS'" in third_query
        assert rows[0]["relation_type"] == "ENABLES"

    @pytest.mark.asyncio
    async def test_get_causes_neo4j_uses_type_r(self):
        pool = MagicMock()
        pool.database_type = DatabaseType.NEO4J.value
        pool.execute_query = AsyncMock(return_value=[])
        repo = CausalGraphRepo(pool)

        await repo.get_causes("target")

        query = pool.execute_query.call_args[0][0]
        assert "type(r) AS relation_type" in query


# ── temporal append idempotency ────────────────


def _event(event_id="evt-1"):
    from modules.memory.core.event_node import EventNode

    return EventNode(
        id=event_id,
        content="content",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestTemporalAppendLadybug:
    @pytest.mark.asyncio
    async def test_linked_node_short_circuits(self):
        """Node already linked → fast path, no writes."""
        pool = _ladybug_pool()
        pool.execute_query = AsyncMock(return_value=[{"id": "evt-1", "linked": 2}])
        repo = TemporalGraphRepo(pool)

        assert await repo.append_to_chain(_event()) is True
        pool.execute_query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_orphan_node_retry_relinks(self):
        """node exists but unlinked → retry still links the chain."""
        pool = _ladybug_pool()
        # check (unlinked) → find_prev → MERGE node → SET props → link
        pool.execute_query = AsyncMock(
            side_effect=[
                [{"id": "evt-1", "linked": 0}],
                [{"prev_id": "prev-1", "prev_time": 1000}],
                [{"e.id": "evt-1"}],
                [],
                [],
            ]
        )
        repo = TemporalGraphRepo(pool)

        assert await repo.append_to_chain(_event()) is True

        link_call = pool.execute_query.await_args_list[4]
        assert "MERGE (prev)-[r:EVENT_FOLLOWED_BY]->(curr)" in link_call[0][0]

    @pytest.mark.asyncio
    async def test_node_creation_uses_merge(self):
        pool = _ladybug_pool()
        pool.execute_query = AsyncMock(
            side_effect=[
                [],
                [],
                [{"e.id": "evt-1"}],
                [],
                [],
            ]
        )
        repo = TemporalGraphRepo(pool)

        await repo.append_to_chain(_event())

        merge_query = pool.execute_query.await_args_list[2][0][0]
        assert "MERGE (e:EventNode {id: $id})" in merge_query
        assert "CREATE (e:EventNode" not in merge_query

    @pytest.mark.asyncio
    async def test_find_prev_excludes_self(self):
        """The chain-tail query must not match the event being appended."""
        pool = _ladybug_pool()
        pool.execute_query = AsyncMock(side_effect=[[], [], [{"e.id": "evt-1"}], [], []])
        repo = TemporalGraphRepo(pool)

        await repo.append_to_chain(_event())

        find_prev_params = pool.execute_query.await_args_list[1][0][1]
        assert find_prev_params == {"id": "evt-1"}
        assert "prev.id <> $id" in pool.execute_query.await_args_list[1][0][0]

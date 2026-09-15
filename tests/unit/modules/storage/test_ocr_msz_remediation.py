# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Regression tests for storage MEDIUM findings.

Each test pins one `fixed` verdict from ``logs/ocr_scan_msz_storage.json``.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_pool_with_session(session):
    """Pool mock whose session() yields the given fake session."""
    pool = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    pool.session = MagicMock(return_value=ctx)
    return pool


class _ScriptedResult:
    """Fake SQLAlchemy result with configurable rowcount/fetchone/all."""

    def __init__(self, rowcount=0, fetchone_value=None, all_value=None):
        self.rowcount = rowcount
        self._fetchone_value = fetchone_value
        self._all_value = all_value if all_value is not None else []

    def fetchone(self):
        return self._fetchone_value

    def all(self):
        return self._all_value

    def scalars(self):
        m = MagicMock()
        m.all.return_value = self._all_value
        m.one_or_none.return_value = self._all_value[0] if self._all_value else None
        return m

    def scalar_one_or_none(self):
        return self._all_value[0] if self._all_value else None

    def __iter__(self):
        return iter(self._all_value)


class _ScriptedSession:
    """Fake AsyncSession replaying scripted results in execute() order."""

    def __init__(self, results):
        self._results = list(results)
        self.executes = []
        self.commits = 0
        self.rollbacks = 0
        self.added = []

    async def execute(self, stmt, params=None):
        self.executes.append(stmt)
        if not self._results:
            raise AssertionError("more execute() calls than scripted results")
        return self._results.pop(0)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def flush(self):
        return None

    def add(self, obj):
        self.added.append(obj)

    def add_all(self, objs):
        self.added.extend(objs)


# ── delete_orphan_entities returns actual deleted count ──────


class _OrphanHarness:
    """Minimal BaseEntityRepo harness (abstracts stubbed out)."""

    def __init__(self, pool, orphan_ids, fail_ids=()):
        from modules.storage.base_entity_repo import BaseEntityRepo

        class Harness(BaseEntityRepo):
            async def _list_orphan_ids(self):
                return list(orphan_ids)

            def _delete_entity_query(self):
                return "DELETE"

            def _entity_id_params(self, entity_id):
                return {"id": entity_id}

            def _orphan_count_query(self):
                return "COUNT"

        Harness.__abstractmethods__ = frozenset()
        self._impl = Harness(pool)
        self._fail_ids = set(fail_ids)
        self.calls = []
        orig = self._impl._pool.execute_query

        async def _execute(query, params=None):
            self.calls.append((query, params))
            if (params or {}).get("id") in self._fail_ids:
                raise RuntimeError("boom")
            return await orig(query, params or {})

        self._impl._pool.execute_query = _execute

    def __getattr__(self, name):
        return getattr(self._impl, name)


class TestDeleteOrphanEntities429:
    @pytest.mark.asyncio
    async def test_returns_actual_deleted_count_on_partial_failure(self):
        """mid-loop failure must not mask the real deleted count."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        harness = _OrphanHarness(pool, ["a", "b", "c"], fail_ids={"b"})

        deleted = await harness.delete_orphan_entities()

        assert deleted == 2
        assert len(harness.calls) == 3

    @pytest.mark.asyncio
    async def test_all_deleted_returns_full_count(self):
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        harness = _OrphanHarness(pool, ["a", "b"])

        assert await harness.delete_orphan_entities() == 2


# ── DuckDB cleanup count via before/after ────────────────────


class TestCleanupRawOlderThan433:
    @pytest.mark.asyncio
    async def test_duckdb_rowcount_minus_one_uses_before_after_count(self):
        """rowcount=-1 must not leak into the return value/log."""
        from modules.storage.duckdb.llm_usage_repo import DuckDBLLMUsageRepo

        count_before = MagicMock()
        count_before.scalar.return_value = 5
        delete_res = MagicMock()
        delete_res.rowcount = -1
        count_after = MagicMock()
        count_after.scalar.return_value = 2
        session = _ScriptedSession([count_before, delete_res, count_after])
        repo = DuckDBLLMUsageRepo(pool=_make_pool_with_session(session))

        removed = await repo.cleanup_raw_older_than(days=2)

        assert removed == 3
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_positive_rowcount_used_directly(self):
        from modules.storage.duckdb.llm_usage_repo import DuckDBLLMUsageRepo

        count_before = MagicMock()
        count_before.scalar.return_value = 4
        delete_res = MagicMock()
        delete_res.rowcount = 4
        session = _ScriptedSession([count_before, delete_res])
        repo = DuckDBLLMUsageRepo(pool=_make_pool_with_session(session))

        assert await repo.cleanup_raw_older_than(days=2) == 4


# ── graph entity reader ────────────────────────────


def _make_entity_reader(rows, cooccurrence_rows=None):
    from modules.storage.graph_readers.entity import GraphEntityReader

    calls = []

    async def _execute(build_fn, params=None):
        calls.append(params)
        if (params or {}).get("targets") is not None:
            return list(cooccurrence_rows or [])
        return list(rows)

    reader = GraphEntityReader(MagicMock(), MagicMock(), _execute)
    return reader, calls


class TestGetEntityRelations434:
    @pytest.mark.asyncio
    async def test_missing_keys_fall_back_to_defaults(self):
        """schema drift must not raise KeyError for the whole call."""
        reader, _ = _make_entity_reader([{"source_article_id": "a1"}])

        relations = await reader.get_entity_relations("E")

        assert relations == [
            {
                "target": "",
                "relation_type": "RELATED_TO",
                "source_article_id": "a1",
                "created_at": None,
            }
        ]


class TestCooccurrenceSkipped99:
    @pytest.mark.asyncio
    async def test_no_extra_round_trip_when_all_weights_computed(self):
        """stored weights > 1.0 make the co-occurrence query dead."""
        rows = [
            {
                "relation_type": "R",
                "direction": "outgoing",
                "target_name": "T1",
                "target_type": "人物",
                "target_description": None,
                "weight": 2.0,
            }
        ]
        reader, calls = _make_entity_reader(rows)

        result = await reader.find_by_relation_types("E", None, None, 50)

        assert result[0]["weight"] == 2.0
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_fallback_query_runs_when_weight_missing(self):
        rows = [
            {
                "relation_type": "R",
                "direction": "outgoing",
                "target_name": "T1",
                "target_type": "人物",
                "target_description": None,
                "weight": 1.0,
            }
        ]
        reader, calls = _make_entity_reader(
            rows, cooccurrence_rows=[{"target_name": "T1", "shared_count": 3}]
        )

        result = await reader.find_by_relation_types("E", None, None, 50)

        assert result[0]["weight"] == 3.0
        assert len(calls) == 2


# ── graph repo fallback ───────────────────────────


def _make_graph_repo(primary_rows=None, primary_error=None, with_fallback=True):
    from modules.storage.graph_repo import GraphRepository

    pool = MagicMock()
    if primary_error is not None:
        pool.execute_query = AsyncMock(side_effect=primary_error)
    else:
        pool.execute_query = AsyncMock(return_value=primary_rows or [])
    qb = MagicMock()
    qb.build_get_entity_query = MagicMock(return_value="PRIMARY-Q")
    fb_qb = MagicMock() if with_fallback else None
    repo = GraphRepository(
        pool, qb, fallback_pool_factory=MagicMock(), fallback_query_builder=fb_qb
    )
    return repo


class TestPrimaryFallback437:
    @pytest.mark.asyncio
    async def test_primary_failure_falls_back_when_configured(self):
        """transient primary error must reach the fallback pool."""
        repo = _make_graph_repo(primary_error=RuntimeError("timeout"))
        fb_pool = MagicMock()
        fb_pool.execute_query = AsyncMock(return_value=[{"id": "fb"}])
        repo._fallback_pool = fb_pool
        repo._fallback_query_builder.build_get_entity_query = MagicMock(return_value="FB-Q")

        result = await repo._execute_with_fallback(lambda qb: qb.build_get_entity_query(), {})

        assert result == [{"id": "fb"}]
        fb_pool.execute_query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_primary_failure_reraises_without_fallback(self):
        """no fallback configured → original error propagates."""
        repo = _make_graph_repo(primary_error=RuntimeError("timeout"), with_fallback=False)

        with pytest.raises(RuntimeError, match="timeout"):
            await repo._execute_with_fallback(lambda qb: qb.build_get_entity_query(), {})


class TestFallbackPoolLock125:
    @pytest.mark.asyncio
    async def test_concurrent_init_runs_factory_once(self):
        """concurrent coroutines must not double-initialize."""
        from modules.storage.graph_repo import GraphRepository

        created = []

        def _factory():
            created.append(1)
            pool = MagicMock()
            pool.startup = AsyncMock()
            return pool

        repo = GraphRepository(MagicMock(), MagicMock(), fallback_pool_factory=_factory)
        repo._fallback_query_builder = MagicMock()
        with patch("core.db.ladybug_schema.initialize_ladybug_schema", new=AsyncMock()):
            await asyncio.gather(*[repo._get_fallback_pool() for _ in range(8)])

        assert len(created) == 1


# ── time_gap None preserved ──────────────────────────────────


class TestFollowedByTimeGap439:
    @pytest.mark.asyncio
    async def test_none_gap_leaves_property_untouched(self):
        """None (unknown) must not be cemented as 0.0."""
        from modules.storage.ladybug.article_repo import LadybugArticleRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        repo = LadybugArticleRepo(pool)

        await repo.create_followed_by_relation("a", "b", time_gap_hours=None)

        query, params = pool.execute_query.call_args[0]
        assert "time_gap_hours" not in params
        assert "SET" not in query

    @pytest.mark.asyncio
    async def test_zero_gap_is_preserved_as_zero(self):
        """explicit 0.0 stays 0.0 (only None is special)."""
        from modules.storage.ladybug.article_repo import LadybugArticleRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        repo = LadybugArticleRepo(pool)

        await repo.create_followed_by_relation("a", "b", time_gap_hours=0.0)

        _, params = pool.execute_query.call_args[0]
        assert params["time_gap_hours"] == 0.0


# ── non-integer tier from DB ─────────────────────────────────


class TestMergeEntityTierCast441:
    @pytest.mark.asyncio
    async def test_string_tier_does_not_raise(self):
        """string tier from DB must not raise TypeError."""
        from modules.storage.ladybug.entity_repo import LadybugEntityRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(
            side_effect=[
                [{"id": "e1", "tier": "1"}],
                [{"id": "e1"}],
            ]
        )
        repo = LadybugEntityRepo(pool)

        assert await repo.merge_entity("E", "人物", tier=2) == "e1"

    @pytest.mark.asyncio
    async def test_garbage_tier_falls_back_to_default(self):
        from modules.storage.ladybug.entity_repo import LadybugEntityRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(
            side_effect=[
                [{"id": "e1", "tier": "not-a-number"}],
                [{"id": "e1"}],
            ]
        )
        repo = LadybugEntityRepo(pool)

        # new tier 1 < default 2 → update path, must not raise
        assert await repo.merge_entity("E", "人物", tier=1) == "e1"


# ── single round-trip relation-type query ────────────────────


class TestFindByRelationTypesSingleQuery101:
    @pytest.mark.asyncio
    async def test_relation_types_use_in_param_single_call(self):
        """N types → 1 query with IN $edge_types."""
        from modules.storage.ladybug.entity_repo import LadybugEntityRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        repo = LadybugEntityRepo(pool)

        await repo.find_by_relation_types("E", None, ["A", "B", "C"], limit=10)

        assert pool.execute_query.await_count == 1
        query, params = pool.execute_query.call_args[0]
        assert params["edge_types"] == ["A", "B", "C"]
        assert "IN $edge_types" in query


# ── writer cache-key normalization ───────────────────────────


class TestWriterCacheNormalization445:
    @pytest.mark.asyncio
    async def test_spaced_relation_endpoints_hit_entity_cache(self):
        """' Alice ' entity must match 'Alice' relation endpoint."""
        from modules.storage.ladybug.writer import LadybugWriter

        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        writer = LadybugWriter(pool)

        entity_repo = MagicMock()
        entity_repo.merge_entity = AsyncMock(return_value="eid-alice")
        entity_repo.merge_mentions_relation = AsyncMock()
        entity_repo.find_entity_by_name = AsyncMock(return_value=None)
        entity_repo.merge_relation = AsyncMock()
        article_repo = MagicMock()
        article_repo.create_article = AsyncMock()
        writer._entity_repo = entity_repo
        writer._article_repo = article_repo

        state = {
            "article_id": "art-1",
            "cleaned": {"title": "T", "body": "B"},
            "entities": [{"canonical_name": "  Alice  ", "type": "人物"}],
            "relations": [{"source": "Alice", "target": "Alice", "relation_type": "KNOWS"}],
        }
        await writer._write_locked(state)

        # Cache hit → no DB lookup and no ghost auto-create for Alice.
        entity_repo.find_entity_by_name.assert_not_called()
        assert entity_repo.merge_entity.await_count == 1
        entity_repo.merge_relation.assert_awaited_once()


# ── atomic orphan delete ─────────────────────────────────────


class TestDeleteOrphanEntitiesAtomic449:
    @pytest.mark.asyncio
    async def test_returns_actual_deleted_count_single_statement(self):
        """one atomic statement reports the real deleted count."""
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"deleted": 3}])
        repo = Neo4jEntityRepo(pool)

        assert await repo.delete_orphan_entities() == 3
        assert pool.execute_query.await_count == 1
        query = pool.execute_query.call_args[0][0]
        assert "size(orphans)" in query
        assert "count_orphan" not in query.lower()

    @pytest.mark.asyncio
    async def test_empty_result_returns_zero(self):
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        repo = Neo4jEntityRepo(pool)

        assert await repo.delete_orphan_entities() == 0


# ── role fallback guard ──────────────────────────────────────


class TestMentionsBatchRoleGuard450:
    @pytest.mark.asyncio
    async def test_null_role_does_not_wipe_stored_role(self):
        """m.role NULL must keep r.role (CASE WHEN guard)."""
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"total": 1}])
        repo = Neo4jEntityRepo(pool)

        await repo.merge_mentions_batch(
            [{"article_id": "a", "entity_name": "E", "entity_type": "人物", "role": None}]
        )

        query = pool.execute_query.call_args[0][0]
        assert "CASE WHEN m.role IS NOT NULL THEN m.role ELSE r.role END" in query


# ── unexpected constraint errors surfaced ────────────────────


class TestEnsureConstraintsWarning451:
    @pytest.mark.asyncio
    async def test_unexpected_error_does_not_raise(self):
        """unexpected failures stay non-fatal (no-raise kept)."""
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(side_effect=RuntimeError("connection reset"))
        repo = Neo4jEntityRepo(pool)

        await repo.ensure_constraints()  # must not raise

    @pytest.mark.asyncio
    async def test_unexpected_error_logged_at_warning(self):
        """unexpected failures surface at WARNING, not debug."""
        from modules.storage.neo4j import entity_repo as entity_repo_module
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(side_effect=RuntimeError("connection reset"))
        repo = Neo4jEntityRepo(pool)

        with patch.object(entity_repo_module, "log") as mock_log:
            await repo.ensure_constraints()

        mock_log.warning.assert_called()
        assert mock_log.debug.call_count == 0


# ── parameterized edge-type filter ────────────────────────────


class TestFindByRelationTypesParam69:
    @pytest.mark.asyncio
    async def test_edge_types_passed_as_param_not_interpolated(self):
        """query shape must not depend on edge-type text."""
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        repo = Neo4jEntityRepo(pool)

        await repo.find_by_relation_types("E", "人物", relation_types=["KNOWS", "WORKS_WITH"])

        query, params = pool.execute_query.call_args[0]
        assert "IN $types" in query
        assert params["types"] == ["KNOWS", "WORKS_WITH"]
        assert "KNOWS" not in query


# ── labeled MATCH in merge_relation ──────────────────────────


class TestMergeRelationLabels102:
    @pytest.mark.asyncio
    async def test_match_uses_entity_label(self):
        """elementId MATCH must carry:Entity for index use."""
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        repo = Neo4jEntityRepo(pool)

        await repo.merge_relation("id-1", "id-2", "KNOWS")

        query = pool.execute_query.call_args[0][0]
        assert "MATCH (from:Entity)" in query
        assert "MATCH (to:Entity)" in query


# ── article reader ────────────────────────────────


class TestGetByIdsSourceId282:
    @pytest.mark.asyncio
    async def test_source_id_preserved(self):
        """RawArticle keeps source_id (not dropped)."""
        from modules.storage.postgres.article_reader import ArticleReader

        article_id = str(uuid.uuid4())
        row = SimpleNamespace(
            source_url="https://example.com/x",
            title="T",
            body="B",
            source_host="example.com",
            source_id="rss-cnbeta",
            publish_time=None,
        )
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        session.execute = AsyncMock(return_value=result)
        reader = ArticleReader(_make_pool_with_session(session))

        raws = await reader.get_by_ids([article_id])

        assert len(raws) == 1
        assert raws[0].source_id == "rss-cnbeta"
        assert raws[0].source == "example.com"


class TestGetExistingUrlsChunked105:
    @pytest.mark.asyncio
    async def test_large_input_is_chunked(self):
        """1200 urls → 3 bounded IN queries, unioned results."""
        from modules.storage.postgres.article_reader import ArticleReader

        session = MagicMock()
        session.execute = AsyncMock(return_value=_ScriptedResult(all_value=[]))
        reader = ArticleReader(_make_pool_with_session(session))

        urls = [f"https://example.com/{i}" for i in range(1200)]
        assert await reader.get_existing_urls(urls) == set()
        assert session.execute.await_count == 3


# ── terminal marking must not clobber processed rows ─────────


class TestMarkTerminalByUrl455:
    def _make_writer(self, results):
        from modules.storage.postgres.article_writer import ArticleWriter

        session = _ScriptedSession(results)
        return ArticleWriter(_make_pool_with_session(session)), session

    @pytest.mark.asyncio
    async def test_no_match_skips_analysis_updates_and_returns_false(self):
        """already-processed article keeps real analysis data."""
        no_row = _ScriptedResult(rowcount=0)
        writer, session = self._make_writer([no_row])

        assert await writer.mark_terminal_by_url("https://example.com/x") is False

        assert len(session.executes) == 1  # core UPDATE only
        assert session.commits == 0
        assert session.rollbacks == 1

    @pytest.mark.asyncio
    async def test_match_updates_analysis_body_and_commits(self):
        ok = _ScriptedResult(rowcount=1)
        writer, session = self._make_writer([ok, ok, ok])

        assert await writer.mark_terminal_by_url("https://example.com/x") is True

        assert len(session.executes) == 3  # core + analysis + body
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_duckdb_rowcount_falls_back_to_verify_select(self):
        """DuckDB rowcount=-1 → verify SELECT decides the match."""
        verify_hit = _ScriptedResult(rowcount=-1)
        verify_select = _ScriptedResult(rowcount=-1, fetchone_value=("id",))
        ok = _ScriptedResult(rowcount=1)
        writer, session = self._make_writer([verify_hit, verify_select, ok, ok])

        assert await writer.mark_terminal_by_url("https://example.com/x") is True
        assert session.commits == 1


# ── atomic final_score update ────────────────────────────────


class TestUpdateAutoScoreAtomic463:
    @pytest.mark.asyncio
    async def test_single_update_with_coalesce_expression(self):
        """no SELECT — final_score computed in the UPDATE."""
        from modules.storage.postgres.source_authority_repo import SourceAuthorityRepo

        session = _ScriptedSession([_ScriptedResult(rowcount=1)])
        repo = SourceAuthorityRepo(_make_pool_with_session(session))

        await repo.update_auto_score("example.com", 0.8)

        assert len(session.executes) == 1
        stmt_str = str(session.executes[0])
        assert "final_score" in stmt_str
        assert "coalesce" in stmt_str.lower()
        assert session.commits == 1


# ── concrete callable alias ──────────────────────────────────


class TestExecuteWithFallbackAlias275:
    def test_alias_is_concrete_generic(self):
        """alias must pin arity/types, not Callable[..., Any]."""
        from typing import get_args

        from modules.storage.graph_readers.base import ExecuteWithFallbackFn

        params, ret = get_args(ExecuteWithFallbackFn)
        assert isinstance(params, list) and len(params) == 2
        assert "list" in repr(ret) and "dict" in repr(ret)


# ── insert_raw shares the helper ─────────────────────────────


class TestInsertRawUsesHelper289:
    @pytest.mark.asyncio
    async def test_short_body_falls_back_to_description(self):
        """insert_raw honors the shared body-fallback logic."""
        from core.db import ArticleBody, ArticleCore
        from core.types.ingestion_models import RawArticle
        from modules.storage.postgres.raw_bulk_writer import RawBulkWriter

        raw = RawArticle(
            url="https://example.com/dup-path",
            title="T",
            body="short",
            source="example.com",
            source_host="example.com",
            description="D" * 300,
        )

        class _Session(_ScriptedSession):
            async def flush(self):
                for obj in self.added:
                    if isinstance(obj, ArticleCore) and obj.id is None:
                        obj.id = uuid.uuid4()

        session = _Session([_ScriptedResult(all_value=[])])
        writer = RawBulkWriter(_make_pool_with_session(session))

        await writer.insert_raw(raw)

        bodies = [o for o in session.added if isinstance(o, ArticleBody)]
        assert len(bodies) == 1
        assert bodies[0].body == "D" * 300
        assert session.commits == 1


# ── atomic chunked upsert ────────────────────────────────────


class TestUpsertEntityVectorsAtomic290:
    @pytest.mark.asyncio
    async def test_multi_chunk_single_session_single_commit(self):
        """2505 vectors → 3 statements, 1 session, 1 commit."""
        from unittest.mock import MagicMock

        from modules.storage.postgres.vector_repo import VectorRepo

        sessions = 0
        executes = 0
        commits = 0

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def execute(self, stmt):
                nonlocal executes
                executes += 1

            async def commit(self):
                nonlocal commits
                commits += 1

        def _session():
            nonlocal sessions
            sessions += 1
            return FakeSession()

        builder = MagicMock()
        builder.database_type = MagicMock()
        builder.database_type.name = "POSTGRES"
        builder.database_type.value = "postgres"
        repo = VectorRepo(pool=MagicMock(), query_builder=builder)
        repo._pool.session = _session

        entities = [(f"E{i}", [0.1] * 4) for i in range(2505)]
        await repo.upsert_entity_vectors(entities, model_id="m1")

        assert executes == 3
        assert sessions == 1
        assert commits == 1


# ── community vector search ─────────────────────────


class TestFindSimilarCommunities106and70:
    def _make_repo(self, session):
        from unittest.mock import MagicMock

        from core.db.query_builders import DatabaseType
        from modules.storage.postgres.community_vector_repo import CommunityVectorRepo

        pool = _make_pool_with_session(session)
        qb = MagicMock()
        qb.database_type = DatabaseType.DUCKDB
        qb.format_embedding_param = MagicMock(return_value="[0.1]")
        return CommunityVectorRepo(pool=pool, query_builder=qb)

    @pytest.mark.asyncio
    async def test_distance_computed_once_via_cte(self):
        """single distance expression reused by filter+order."""
        result = MagicMock()
        result.all = MagicMock(return_value=[])
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        repo = self._make_repo(session)

        await repo.find_similar_communities(embedding=[0.1] * 8)

        query = str(session.execute.await_args_list[0].args[0])
        assert "WITH sim AS" in query
        assert query.count("<=>") == 1

    @pytest.mark.asyncio
    async def test_invalid_limit_rejected(self):
        """huge/zero limits must not reach the HNSW scan."""
        session = MagicMock()
        session.execute = AsyncMock()
        repo = self._make_repo(session)

        with pytest.raises(ValueError):
            await repo.find_similar_communities(embedding=[0.1], limit=100000)
        with pytest.raises(ValueError):
            await repo.find_similar_communities(embedding=[0.1], limit=0)
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_threshold_rejected(self):
        session = MagicMock()
        session.execute = AsyncMock()
        repo = self._make_repo(session)

        with pytest.raises(ValueError):
            await repo.find_similar_communities(embedding=[0.1], threshold=1.5)
        session.execute.assert_not_called()


# ── bounded stale-pending query ──────────────────────────────


class TestGetStalePendingLimit107:
    @pytest.mark.asyncio
    async def test_limit_applied(self):
        """stale backlog must not load unbounded."""
        from modules.storage.postgres.pending_sync_repo import PendingSyncRepo

        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result)
        repo = PendingSyncRepo(_make_pool_with_session(session))

        await repo.get_stale_pending(hours=1, limit=25)

        stmt_str = str(session.execute.await_args_list[0].args[0])
        assert "LIMIT" in stmt_str.upper()

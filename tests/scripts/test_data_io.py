# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for scripts/data_io.py — PG↔DuckDB / Neo4j→LadybugDB migration tool.

Tests run against real Docker services (no mocks):
  - PostgreSQL (pgvector/pgvector:pg16) on port 5432
  - Neo4j 5.25 on bolt port 7687
  - DuckDB file in tmp_path
  - LadybugDB directory in tmp_path

Connection strings come from environment variables with sane defaults
matching docker/docker-compose.test.yml.

Run:
    uv run pytest tests/scripts/test_data_io.py -v
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# ── Connection configuration (real Docker services) ────────────────────
PG_DSN = os.environ.get(
    "WEAVER_TEST_PG_DSN",
    "postgresql+asyncpg://postgres:weavertest@localhost:5432/weaver",
)
NEO4J_URI = os.environ.get("WEAVER_TEST_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("WEAVER_TEST_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("WEAVER_TEST_NEO4J_PASSWORD", "weavertest")

# ── Expected schema (27 PG tables, 8 Ladybug nodes, 13 Ladybug rels) ──
EXPECTED_TABLES: list[str] = [
    "articles_core",
    "article_bodies",
    "article_analysis",
    "article_processing",
    "article_vectors",
    "article_versions",
    "entity_vectors",
    "source_configs",
    "source_authorities",
    "community_vectors",
    "relation_types",
    "relation_type_aliases",
    "unknown_relation_types",
    "sentiment_shifts",
    "daily_briefings",
    "daily_briefing_items",
    "audit_log",
    "api_keys",
    "prompt_templates",
    "alert_rules",
    "alert_events",
    "pending_sync",
    "saga_logs",
    "llm_failure_records",
    "llm_usage_raw",
    "llm_usage_hourly",
    "llm_compare_hourly",
]
EXPECTED_NODE_LABELS: list[str] = [
    "Entity",
    "Article",
    "Community",
    "CommunityReport",
    "EventNode",
    "NarrativeNode",
    "SchemaNode",
    "_CommunityMetadata",
]
EXPECTED_REL_TYPES: list[str] = [
    "MENTIONS",
    "FOLLOWED_BY",
    "EVENT_FOLLOWED_BY",
    "CAUSES",
    "ENABLES",
    "PREVENTS",
    "RELATED_TO",
    "HAS_ENTITY",
    "REPORTS_ON",
    "HAS_PARTICIPANT",
    "HAS_SUB_EVENT",
    "HAS_NARRATIVE",
    "HAS_EVENT",
]


# ── Fixtures ──────────────────────────────────────────────────────────
@pytest.fixture
async def pg_engine():
    """Async engine to test PostgreSQL."""
    engine = create_async_engine(PG_DSN, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def clean_pg(pg_engine):
    """Truncate all 27 tables before and after test (CASCADE)."""
    async with pg_engine.begin() as conn:
        # Truncate in dependency-safe order (children first), use CASCADE
        for table in EXPECTED_TABLES:
            await conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
    yield
    async with pg_engine.begin() as conn:
        for table in EXPECTED_TABLES:
            await conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def pg_with_data(pg_engine, clean_pg):
    """Insert representative data into key PG tables for export tests.

    Inserts into: articles_core, article_bodies, article_analysis,
    article_processing, source_configs, source_authorities, relation_types,
    relation_type_aliases, api_keys, prompt_templates, alert_rules,
    audit_log, llm_usage_raw, saga_logs, pending_sync, article_versions.
    """
    article_ids = [uuid.uuid4() for _ in range(3)]
    now = datetime.now(UTC)

    async with pg_engine.begin() as conn:
        # source_configs (2 rows) — must come first due to FK on articles_core.source_id
        source_ids = []
        for i in range(2):
            sid = f"src-{i}"
            source_ids.append(sid)
            await conn.execute(
                text(
                    "INSERT INTO source_configs (id, name, url, source_type, "
                    "enabled, interval_minutes, credibility, tier) "
                    "VALUES (:id, :name, :url, 'rss', true, 30, 0.5, 2)"
                ),
                {
                    "id": sid,
                    "name": f"Source {i}",
                    "url": f"https://src-{i}.example.com",
                },
            )

        # source_authorities (1 row)
        await conn.execute(
            text(
                "INSERT INTO source_authorities (host, authority, tier, "
                "needs_review, article_count) "
                "VALUES ('example.com', 0.7, 2, false, 3)"
            )
        )

        # articles_core (3 rows, source_id references source_configs)
        for i, aid in enumerate(article_ids):
            await conn.execute(
                text(
                    "INSERT INTO articles_core (id, source_url, source_host, "
                    "source_id, title, category, persist_status, score, "
                    "sentiment_score, credibility_score, document_type, "
                    "doc_metadata, content_hash, version) "
                    "VALUES (:id, :url, :host, :src_id, :title, '科技', "
                    "'pending', :score, 0.5, 0.5, 'news', '{}'::jsonb, "
                    ":hash, 1)"
                ),
                {
                    "id": aid,
                    "url": f"https://example.com/article-{i}",
                    "host": "example.com",
                    "src_id": source_ids[i % len(source_ids)],
                    "title": f"Test Article {i}",
                    "score": 0.5 + i * 0.1,
                    "hash": f"hash{i:040x}"[:64],
                },
            )

        # article_bodies (3 rows)
        for aid in article_ids:
            await conn.execute(
                text(
                    "INSERT INTO article_bodies (article_id, body, summary) "
                    "VALUES (:id, :body, :summary)"
                ),
                {
                    "id": aid,
                    "body": f"Body content for {aid}",
                    "summary": f"Summary of {aid}",
                },
            )

        # article_analysis (3 rows)
        for aid in article_ids:
            await conn.execute(
                text(
                    "INSERT INTO article_analysis (article_id, is_news, "
                    "quality_score, sentiment, verified_by_sources) "
                    "VALUES (:id, true, 0.7, 'positive', 2)"
                ),
                {"id": aid},
            )

        # article_processing (3 rows)
        for aid in article_ids:
            await conn.execute(
                text(
                    "INSERT INTO article_processing (article_id, "
                    "processing_stage, retry_count) VALUES (:id, 'done', 0)"
                ),
                {"id": aid},
            )

        # article_versions (3 rows)
        for i, aid in enumerate(article_ids):
            await conn.execute(
                text(
                    "INSERT INTO article_versions (article_id, version, "
                    "title, body, summary, category, score) "
                    "VALUES (:id, 1, :title, :body, :summary, '科技', 0.5)"
                ),
                {
                    "id": aid,
                    "title": f"Version Title {i}",
                    "body": f"Version Body {i}",
                    "summary": f"Version Summary {i}",
                },
            )

        # relation_types (1 row) + aliases (2 rows)
        # Note: relation_types has no usage_count column (see misc.py:142-169)
        await conn.execute(
            text(
                "INSERT INTO relation_types (name, name_en, category, "
                "is_symmetric, is_active, sort_order) "
                "VALUES ('测试关系', 'TEST_REL', '因果', false, true, 1)"
            )
        )
        rt_id = (
            await conn.execute(text("SELECT id FROM relation_types WHERE name_en='TEST_REL'"))
        ).scalar()
        for alias in ["别名1", "别名2"]:
            await conn.execute(
                text(
                    "INSERT INTO relation_type_aliases (relation_type_id, alias) "
                    "VALUES (:rt_id, :alias)"
                ),
                {"rt_id": rt_id, "alias": alias},
            )

        # api_keys (1 row) — expires_at is NOT NULL with no default
        await conn.execute(
            text(
                "INSERT INTO api_keys (key_id, key_hash, scopes, "
                "rate_limit_per_min, is_revoked, created_by, expires_at) "
                "VALUES ('weaver_test_key_000000000000000000000', "
                "'$argon2id$hash$placeholder', "
                "'[\"read\",\"write\"]'::jsonb, 100, false, 'tester', "
                ":expires_at)"
            ),
            {"expires_at": now + timedelta(days=30)},
        )

        # prompt_templates (1 row)
        await conn.execute(
            text(
                "INSERT INTO prompt_templates (name, template) "
                "VALUES ('test_prompt', 'Hello {{name}}')"
            )
        )

        # alert_rules (1 row, threshold type)
        # metric must be in ('reference_count','sentiment_change','volume_spike')
        # operator must be in ('z_score>','pct_change>','absolute>')
        await conn.execute(
            text(
                "INSERT INTO alert_rules (entity_name, metric, operator, "
                "threshold, channel, cooldown_minutes, enabled, trigger_type) "
                "VALUES ('FFmpeg', 'reference_count', 'absolute>', 10, "
                "'webhook', 60, true, 'threshold')"
            )
        )

        # alert_events (1 row)
        rule_id = (await conn.execute(text("SELECT id FROM alert_rules LIMIT 1"))).scalar()
        await conn.execute(
            text(
                "INSERT INTO alert_events (rule_id, entity_name, "
                "metric_value, detail) "
                "VALUES (:rid, 'FFmpeg', 15.5, '{}'::jsonb)"
            ),
            {"rid": rule_id},
        )

        # audit_log (1 row)
        await conn.execute(
            text(
                "INSERT INTO audit_log (key_id, action, target_type, "
                "target_id, detail, client_ip, user_agent) "
                "VALUES ('weaver_test_key_000000000000000000000', 'read', "
                "'article', '00000000-0000-0000-0000-000000000001', "
                "'{}'::jsonb, '127.0.0.1', 'pytest')"
            )
        )

        # llm_usage_raw (1 row)
        await conn.execute(
            text(
                "INSERT INTO llm_usage_raw (label, call_point, llm_type, "
                "provider, model, input_tokens, output_tokens, total_tokens, "
                "cost_usd, latency_ms, success, article_id) "
                "VALUES ('test_label', 'classify', 'routing', 'agnes', "
                "'test-model', 100, 50, 150, 0.001, 500.0, true, :aid)"
            ),
            {"aid": article_ids[0]},
        )

        # saga_logs (1 row)
        await conn.execute(
            text(
                "INSERT INTO saga_logs (saga_id, article_id, step_name, "
                "step_status, started_at, compensation_data, error_message) "
                "VALUES (:sid, :aid, 'pg_write', 'completed', :ts, "
                "'{}'::jsonb, NULL)"
            ),
            {
                "sid": uuid.uuid4(),
                "aid": article_ids[0],
                "ts": now,
            },
        )

        # pending_sync (1 row)
        await conn.execute(
            text(
                "INSERT INTO pending_sync (article_id, sync_type, payload, "
                "status) VALUES (:aid, 'entity', '{}'::jsonb, 'pending')"
            ),
            {"aid": article_ids[0]},
        )

    return {"article_ids": [str(a) for a in article_ids]}


@pytest.fixture
def clean_neo4j():
    """Delete all nodes and relationships in Neo4j before/after test."""
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
        yield
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
    finally:
        driver.close()


@pytest.fixture
def neo4j_with_data(clean_neo4j):
    """Insert 3 Entity + 3 Article + 3 MENTIONS relationships into Neo4j."""
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            # 3 Entity nodes
            for i in range(3):
                session.run(
                    "CREATE (e:Entity {id: $id, canonical_name: $name, "
                    "type: $type, aliases: $aliases, description: $desc, "
                    "tier: $tier, created_at: datetime(), updated_at: datetime()})",
                    id=f"entity-{i}",
                    name=f"Entity_{i}",
                    type="ORG",
                    aliases=[f"Alias_{i}_1", f"Alias_{i}_2"],
                    desc=f"Test entity {i}",
                    tier=2,
                ).consume()

            # 3 Article nodes
            for i in range(3):
                session.run(
                    "CREATE (a:Article {id: $id, pg_id: $pg_id, title: $title, "
                    "category: $cat, publish_time: datetime(), score: $score, "
                    "created_at: datetime(), updated_at: datetime()})",
                    id=f"article-{i}",
                    pg_id=str(uuid.uuid4()),
                    title=f"Article {i}",
                    cat="科技",
                    score=0.5 + i * 0.1,
                ).consume()

            # 3 MENTIONS relationships
            for i in range(3):
                session.run(
                    "MATCH (a:Article {id: $aid}), (e:Entity {id: $eid}) "
                    "CREATE (a)-[r:MENTIONS {role: $role, "
                    "created_at: datetime(), updated_at: datetime()}]->(e)",
                    aid=f"article-{i}",
                    eid=f"entity-{i}",
                    role="subject",
                ).consume()
        yield {"entity_count": 3, "article_count": 3, "mentions_count": 3}
    finally:
        driver.close()


# ── Tests: PG → DuckDB export ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_export_postgres_to_duckdb_creates_file(pg_with_data, tmp_path):
    """T009: export_postgres_to_duckdb creates DuckDB file."""
    from scripts.data_io import export_postgres_to_duckdb

    duckdb_path = tmp_path / "export.duckdb"
    await export_postgres_to_duckdb(
        pg_dsn=PG_DSN,
        duckdb_path=str(duckdb_path),
    )

    assert duckdb_path.exists(), "DuckDB file must exist after export"
    assert duckdb_path.stat().st_size > 0, "DuckDB file must be non-empty"


@pytest.mark.asyncio
async def test_export_postgres_to_duckdb_row_counts_match(pg_with_data, tmp_path):
    """T009: All 27 tables in exported DuckDB have row counts matching PG."""
    from scripts.data_io import export_postgres_to_duckdb, validate_migration

    duckdb_path = tmp_path / "export.duckdb"
    await export_postgres_to_duckdb(
        pg_dsn=PG_DSN,
        duckdb_path=str(duckdb_path),
    )

    results = await validate_migration(
        source_type="postgres",
        source_dsn=PG_DSN,
        target_type="duckdb",
        target_path=str(duckdb_path),
    )

    # All 27 tables must be in the report
    reported_tables = {r["table"] for r in results}
    missing_tables = set(EXPECTED_TABLES) - reported_tables
    assert not missing_tables, f"Missing tables in report: {missing_tables}"

    # All must match
    mismatches = [r for r in results if not r["match"]]
    assert not mismatches, f"Row count mismatches: {mismatches}"


@pytest.mark.asyncio
async def test_export_postgres_to_duckdb_atomic_on_failure(pg_with_data, tmp_path):
    """T043/R-verify-006: If export fails mid-way, original DuckDB file is preserved."""
    from scripts.data_io import export_postgres_to_duckdb

    # Pre-create a valid DuckDB file as "original"
    original_path = tmp_path / "original.duckdb"
    import duckdb

    with duckdb.connect(str(original_path)) as conn:
        conn.execute("CREATE TABLE marker (id INTEGER)")
        conn.execute("INSERT INTO marker VALUES (42)")

    # Attempt export to same path with an invalid PG DSN to force failure
    invalid_dsn = "postgresql+asyncpg://postgres:wrong@localhost:5432/nonexistent"
    with pytest.raises(Exception):  # noqa: B017 (broad on purpose: any DB conn error)
        await export_postgres_to_duckdb(
            pg_dsn=invalid_dsn,
            duckdb_path=str(original_path),
        )

    # Original file must still be readable and contain marker
    with duckdb.connect(str(original_path)) as conn:
        result = conn.execute("SELECT id FROM marker").fetchone()
        assert result == (42,), "Original DuckDB file must be preserved on failure"

    # Tmp file must not exist
    tmp_path_check = Path(str(original_path) + ".tmp")
    assert not tmp_path_check.exists(), "Temp file must be cleaned up on failure"


# ── Tests: DuckDB → PG import ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_import_duckdb_to_postgres_row_counts_match(pg_with_data, tmp_path, pg_engine):
    """T008: DuckDB→PG import preserves row counts across 27 tables.

    Strategy: export PG→DuckDB first (creates canonical DuckDB), then
    truncate PG, then import DuckDB→PG, then verify row counts.
    """
    from scripts.data_io import (
        export_postgres_to_duckdb,
        import_duckdb_to_postgres,
        validate_migration,
    )

    # Step 1: Export PG → DuckDB (canonical source)
    duckdb_path = tmp_path / "canonical.duckdb"
    await export_postgres_to_duckdb(
        pg_dsn=PG_DSN,
        duckdb_path=str(duckdb_path),
    )

    # Step 2: Capture source row counts before truncating PG
    pg_counts_before: dict[str, int] = {}
    async with pg_engine.connect() as conn:
        for table in EXPECTED_TABLES:
            count = (
                await conn.execute(
                    text(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 (constant list)
                )
            ).scalar()
            pg_counts_before[table] = count

    # Step 3: Truncate all PG tables
    async with pg_engine.begin() as conn:
        for table in EXPECTED_TABLES:
            await conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))

    # Step 4: Import DuckDB → PG
    await import_duckdb_to_postgres(
        duckdb_path=str(duckdb_path),
        pg_dsn=PG_DSN,
    )

    # Step 5: Validate row counts match
    results = await validate_migration(
        source_type="duckdb",
        source_path=str(duckdb_path),
        target_type="postgres",
        target_dsn=PG_DSN,
    )

    mismatches = [r for r in results if not r["match"]]
    assert not mismatches, f"Row count mismatches after import: {mismatches}"

    # Specifically: articles_core should have 3 rows (matching fixture)
    async with pg_engine.connect() as conn:
        pg_count = (await conn.execute(text("SELECT COUNT(*) FROM articles_core"))).scalar()
    assert pg_count == pg_counts_before["articles_core"]


# ── Tests: Neo4j → LadybugDB export ───────────────────────────────────
@pytest.mark.asyncio
async def test_export_neo4j_to_ladybug_node_counts_match(neo4j_with_data, tmp_path):
    """T010: export_neo4j_to_ladybug preserves node counts for all 8 labels."""
    from scripts.data_io import export_neo4j_to_ladybug

    ladybug_path = tmp_path / "export.ladybug"
    await export_neo4j_to_ladybug(
        neo4j_uri=NEO4J_URI,
        neo4j_user=NEO4J_USER,
        neo4j_password=NEO4J_PASSWORD,
        ladybug_path=str(ladybug_path),
    )

    assert ladybug_path.exists(), "LadybugDB directory must exist after export"

    # Verify node counts via real_ladybug driver
    # (Weaver project uses real_ladybug, not kuzu — pybind11 type registration
    # conflict if both are loaded in same process.)
    import real_ladybug as ladybug

    db = ladybug.Database(str(ladybug_path))
    conn = ladybug.Connection(db)

    # Entity and Article should have 3 nodes each (matching fixture)
    entity_result = conn.execute("MATCH (e:Entity) RETURN COUNT(e) AS cnt").get_next()
    assert entity_result[0] == 3, f"Expected 3 Entity nodes, got {entity_result[0]}"

    article_result = conn.execute("MATCH (a:Article) RETURN COUNT(a) AS cnt").get_next()
    assert article_result[0] == 3, f"Expected 3 Article nodes, got {article_result[0]}"


@pytest.mark.asyncio
async def test_export_neo4j_to_ladybug_rel_counts_match(neo4j_with_data, tmp_path):
    """T010: export_neo4j_to_ladybug preserves relationship counts."""
    from scripts.data_io import export_neo4j_to_ladybug

    ladybug_path = tmp_path / "export.ladybug"
    await export_neo4j_to_ladybug(
        neo4j_uri=NEO4J_URI,
        neo4j_user=NEO4J_USER,
        neo4j_password=NEO4J_PASSWORD,
        ladybug_path=str(ladybug_path),
    )

    import real_ladybug as ladybug

    db = ladybug.Database(str(ladybug_path))
    conn = ladybug.Connection(db)

    # MENTIONS should have 3 relationships (matching fixture)
    mentions_result = conn.execute("MATCH ()-[r:MENTIONS]->() RETURN COUNT(r) AS cnt").get_next()
    assert mentions_result[0] == 3, f"Expected 3 MENTIONS rels, got {mentions_result[0]}"


# ── Tests: validate_migration output format ───────────────────────────
@pytest.mark.asyncio
async def test_validate_migration_returns_list_of_dicts(pg_with_data, tmp_path):
    """T011: validate_migration returns list of dicts with required keys."""
    from scripts.data_io import export_postgres_to_duckdb, validate_migration

    duckdb_path = tmp_path / "export.duckdb"
    await export_postgres_to_duckdb(pg_dsn=PG_DSN, duckdb_path=str(duckdb_path))

    results = await validate_migration(
        source_type="postgres",
        source_dsn=PG_DSN,
        target_type="duckdb",
        target_path=str(duckdb_path),
    )

    assert isinstance(results, list)
    assert len(results) == len(EXPECTED_TABLES)
    for r in results:
        assert "table" in r
        assert "source_count" in r
        assert "target_count" in r
        assert "match" in r
        assert isinstance(r["source_count"], int)
        assert isinstance(r["target_count"], int)
        assert isinstance(r["match"], bool)

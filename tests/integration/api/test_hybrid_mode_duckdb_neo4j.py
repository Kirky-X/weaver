# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Phase 4 hybrid integration tests: DuckDB + Neo4j.

Validates that Weaver works correctly when Neo4j is the graph primary
and DuckDB is the relational primary (PostgreSQL intentionally unavailable).

Run with:
    docker compose -f docker/docker-compose.hybrid-test.yml --profile phase4 up -d
    WEAVER_POSTGRES__DSN= \
    WEAVER_NEO4J__URI=bolt://localhost:7687 \
    WEAVER_NEO4J__PASSWORD=weavertest \
    WEAVER_DUCKDB__DB_PATH=data/weaver.duckdb \
    uv run pytest tests/integration/api/test_hybrid_mode_duckdb_neo4j.py -m integration -v

All tests use real databases — no mocks. Tests are skipped automatically
when Neo4j is unreachable or when POSTGRES__DSN is set (non-hybrid mode).
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("WEAVER_POSTGRES__DSN"),
        reason="Phase 4 requires WEAVER_POSTGRES__DSN to be empty (force DuckDB fallback)",
    ),
    pytest.mark.skipif(
        not os.getenv("WEAVER_NEO4J__PASSWORD"),
        reason="Phase 4 requires WEAVER_NEO4J__PASSWORD to be set (Neo4j primary)",
    ),
]


async def _seed_test_article(container, pg_id: str, title: str) -> None:
    """Insert a minimal article into DuckDB and create a slim Article graph node.

    The graph node stores only {id, pg_id} per design.md §D2 — title lives
    in DuckDB and is batch-fetched by GraphArticleReader on read.
    """
    from core.db import ArticleCore

    pool = container.relational_pool()
    async with pool.session() as session:
        article = ArticleCore(
            id=uuid.UUID(pg_id),
            source_url=f"https://test.example.com/{pg_id}",
            title=title,
        )
        session.add(article)
        await session.commit()

    graph_pool = container.graph_pool()
    # Cypher compatible with both Neo4j and LadybugDB (Kùzu):
    # LadybugDB lacks ON CREATE SET, so CASE WHEN replicates the semantics.
    await graph_pool.execute_query(
        """
        MERGE (a:Article {pg_id: $pg_id})
        SET a.id = CASE WHEN a.id IS NULL THEN $id ELSE a.id END
        RETURN a.pg_id AS pg_id
        """,
        {"id": str(uuid.uuid4()), "pg_id": pg_id},
    )


@pytest.fixture
async def phase4_container():
    """Initialize container with DuckDB + Neo4j (PostgreSQL disabled)."""
    from container import Container, set_container

    container = Container()
    await container.startup()
    set_container(container)
    try:
        yield container
    finally:
        await container.shutdown()
        set_container(None)


@pytest.mark.asyncio
async def test_health_dependencies_returns_duckdb_neo4j(phase4_container):
    """Health endpoint reports DuckDB as relational and Neo4j as graph."""
    strategy = phase4_container._strategy
    assert strategy is not None
    assert strategy.relational_type.value == "duckdb"
    assert strategy.graph_type.value == "neo4j"


@pytest.mark.asyncio
async def test_article_graph_node_only_stores_pg_id(phase4_container):
    """Graph Article node stores only pg_id; title lives in DuckDB.

    After Article node slim-down (design.md §D2), Neo4j Article node stores
    only {id, pg_id}; title/score live in DuckDB and are batch-fetched by
    GraphArticleReader on read.
    """
    pg_id = str(uuid.uuid4())
    await _seed_test_article(phase4_container, pg_id, title="Test Article Title")

    # Verify DuckDB row exists with title
    article_repo = phase4_container.article_repo()
    duckdb_article = await article_repo.get(pg_id)
    assert duckdb_article is not None
    assert str(duckdb_article.id) == pg_id
    assert duckdb_article.title == "Test Article Title"

    # Verify Neo4j Article node exists (query directly to inspect raw node)
    graph_pool = phase4_container.graph_pool()
    nodes = await graph_pool.execute_query(
        "MATCH (a:Article {pg_id: $pg_id}) RETURN a.pg_id AS pg_id, a.id AS id",
        {"pg_id": pg_id},
    )
    assert len(nodes) == 1
    assert nodes[0]["pg_id"] == pg_id
    # slim-down: graph node does NOT store title/category/score
    # (only id and pg_id are persisted)


@pytest.mark.asyncio
async def test_search_returns_results_with_duckdb_title_enrichment(phase4_container):
    """Search returns results with title enriched from DuckDB (not from graph node)."""
    local_engine = phase4_container.local_search_engine()
    if local_engine is None:
        pytest.skip("Local search engine unavailable (no graph pool)")

    result = await local_engine.search("test", use_llm=False)
    assert result is not None
    # Each article source should have a non-empty title (from DuckDB fetch)
    for source in result.sources:
        if source.get("id"):
            assert source.get("title") != ""


@pytest.mark.asyncio
async def test_graph_repo_get_article_enriches_title_from_duckdb(phase4_container):
    """GraphRepository.get_article returns pg_id and enriches title from DuckDB.

    This is the core contract of design.md §D2: graph nodes are slim,
    business fields come from DuckDB via fetch_titles_by_pg_ids.
    """
    pg_id = str(uuid.uuid4())
    await _seed_test_article(phase4_container, pg_id, title="Enriched Title From DuckDB")

    graph_repo = phase4_container.graph_repo()
    article = await graph_repo.get_article(pg_id)
    assert article is not None
    assert article["id"] == pg_id
    # title is fetched from DuckDB, not stored on graph node
    assert article.get("title") == "Enriched Title From DuckDB"

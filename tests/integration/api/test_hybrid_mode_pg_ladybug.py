# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Phase 3 hybrid integration tests: PostgreSQL + LadybugDB.

Validates that Weaver works correctly when PG is the relational primary
and LadybugDB is the graph primary (Neo4j intentionally unavailable).

Run with:
    docker compose -f docker/docker-compose.hybrid-test.yml --profile phase3 up -d
    WEAVER_POSTGRES__DSN=postgresql+asyncpg://postgres:weavertest@localhost:5432/weaver \
    WEAVER_NEO4J__PASSWORD= \
    uv run pytest tests/integration/api/test_hybrid_mode_pg_ladybug.py -m integration -v

All tests use real databases — no mocks. Tests are skipped automatically
when PG is unreachable or when NEO4J__PASSWORD is set (non-hybrid mode).
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("WEAVER_POSTGRES__DSN"),
        reason="Phase 3 requires WEAVER_POSTGRES__DSN to be set",
    ),
    pytest.mark.skipif(
        os.getenv("WEAVER_NEO4J__PASSWORD"),
        reason="Phase 3 requires WEAVER_NEO4J__PASSWORD to be empty (force LadybugDB fallback)",
    ),
]


async def _seed_test_article(container, pg_id: str, title: str) -> None:
    """Insert a minimal article into PG and create a slim Article graph node.

    The graph node stores only {id, pg_id} per design.md §D2 — title lives
    in PG and is batch-fetched by GraphArticleReader on read.
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
async def phase3_container():
    """Initialize container with PG + LadybugDB (Neo4j disabled)."""
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
async def test_health_dependencies_returns_pg_ladybug(phase3_container):
    """Health endpoint reports PG as relational and LadybugDB as graph."""
    strategy = phase3_container._strategy
    assert strategy is not None
    assert strategy.relational_type.value == "postgres"
    assert strategy.graph_type.value == "ladybug"


@pytest.mark.asyncio
async def test_article_graph_node_only_stores_pg_id(phase3_container):
    """Graph Article node stores only pg_id; title lives in PG.

    After Article node slim-down (design.md §D2), LadybugDB Article node
    stores only {id, pg_id}; title/score live in PG and are batch-fetched
    by GraphArticleReader on read.
    """
    pg_id = str(uuid.uuid4())
    await _seed_test_article(phase3_container, pg_id, title="Test Article Title")

    # Verify PG row exists with title
    article_repo = phase3_container.article_repo()
    pg_article = await article_repo.get(pg_id)
    assert pg_article is not None
    assert str(pg_article.id) == pg_id
    assert pg_article.title == "Test Article Title"

    # Verify graph Article node exists (query directly to inspect raw node)
    graph_pool = phase3_container.graph_pool()
    nodes = await graph_pool.execute_query(
        "MATCH (a:Article {pg_id: $pg_id}) RETURN a.pg_id AS pg_id, a.id AS id",
        {"pg_id": pg_id},
    )
    assert len(nodes) == 1
    assert nodes[0]["pg_id"] == pg_id
    # slim-down: graph node does NOT store title/category/score
    # (only id and pg_id are persisted)


@pytest.mark.asyncio
async def test_search_returns_results_with_pg_title_enrichment(phase3_container):
    """Search returns results with title enriched from PG (not from graph node)."""
    local_engine = phase3_container.local_search_engine()
    if local_engine is None:
        pytest.skip("Local search engine unavailable (no graph pool)")

    result = await local_engine.search("test", use_llm=False)
    assert result is not None
    # Each article source should have a non-empty title (from PG fetch)
    for source in result.sources:
        if source.get("id"):
            assert source.get("title") != ""


@pytest.mark.asyncio
async def test_graph_repo_get_article_enriches_title_from_pg(phase3_container):
    """GraphRepository.get_article returns pg_id and enriches title from PG.

    This is the core contract of design.md §D2: graph nodes are slim,
    business fields come from PG via fetch_titles_by_pg_ids.
    """
    pg_id = str(uuid.uuid4())
    await _seed_test_article(phase3_container, pg_id, title="Enriched Title From PG")

    graph_repo = phase3_container.graph_repo()
    article = await graph_repo.get_article(pg_id)
    assert article is not None
    assert article["id"] == pg_id
    # title is fetched from PG, not stored on graph node
    assert article.get("title") == "Enriched Title From PG"

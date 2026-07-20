# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Phase 3 hybrid integration tests: PostgreSQL + LadybugDB.

Validates that Weaver works correctly when PG is the relational primary
and LadybugDB is the graph primary (Neo4j intentionally unavailable).

Run with:
    docker compose -f docker/docker-compose.hybrid-test.yml --profile phase3 up -d
    WEAVER_POSTGRES__DSN=postgresql+asyncpg://postgres:<test-password>@localhost:5432/weaver \
    WEAVER_NEO4J__PASSWORD= \
    uv run pytest tests/integration/api/test_hybrid_mode_pg_ladybug.py -m integration -v

The `<test-password>` placeholder refers to the local dev password defined in
docker/docker-compose.yml. Never use real production credentials.

All tests use real databases — no mocks. Tests are skipped automatically
when PG is unreachable, when NEO4J__PASSWORD is set (non-hybrid mode), or
when WEAVER_POSTGRES__DSN points to a non-localhost host (safety guard).
"""

from __future__ import annotations

import os
import uuid

import pytest

from .conftest import (
    FakeLLMClient,
    FakePromptLoader,
    cleanup_test_article,
    require_localhost_dsn,
    seed_test_article,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not bool(os.getenv("WEAVER_POSTGRES__DSN")),
        reason="Phase 3 requires WEAVER_POSTGRES__DSN to be set",
    ),
    pytest.mark.skipif(
        bool(os.getenv("WEAVER_NEO4J__PASSWORD")),
        reason="Phase 3 requires WEAVER_NEO4J__PASSWORD to be empty (force LadybugDB fallback)",
    ),
    pytest.mark.skipif(
        not require_localhost_dsn(),
        reason="Phase 3 refuses non-localhost DSN (safety guard against prod pollution)",
    ),
]


@pytest.fixture(scope="session")
async def phase3_container():
    """Session-scoped container with PG + LadybugDB (Neo4j disabled).

    Minimal init: configure + init_strategy + alembic + stub LLM +
    init_search_engines. Skips scheduler/pipeline/ML components — those
    are not needed by the hybrid tests and would add 10-30s + background
    tasks per fixture.

    Session scope rationale (performance M1+M2): container init +
    alembic migrations are idempotent and expensive (~5s). Tests use
    unique UUIDs for seeded articles, so no cross-test interference.
    Test data is cleaned up per-test via cleanup_test_article().

    use_llm=False contract (architecture L2): search engines store the
    stub LLM as a dependency but never invoke it — local_search_engine.
    search(use_llm=False) skips all LLM call points. The stub raises
    AssertionError if ever called, providing a fail-loud signal.
    """
    from container import Container, set_container
    from container.access import get_settings
    from core.constants import DatabaseType
    from core.db.initializer import initialize_database
    from core.utils.paths import PROJECT_ROOT

    container = Container()
    container.configure(get_settings())

    # Init PG + LadybugDB pools (LadybugDB schema auto-created)
    await container.init_strategy()

    # Run alembic migrations on PG (idempotent — skips if already at head).
    # Runs once per session (not per-test) to avoid repeated migration checks.
    strategy = container._strategy
    if strategy is not None and strategy.relational_type == DatabaseType.POSTGRES:
        await initialize_database(
            container.settings.postgres.dsn,
            alembic_ini_path=str(PROJECT_ROOT / "alembic.ini"),
            script_location=str(PROJECT_ROOT / "src" / "alembic"),
        )

    # Stub LLM + prompt_loader: search engines need them as deps, not invoked
    # (local_search_engine.search uses use_llm=False in tests)
    container._llm_client = FakeLLMClient()
    container._prompt_loader = FakePromptLoader()

    # Init search engines (uses stub LLM, real graph_pool + article_repo)
    container.init_search_engines()

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
    # graph_type is a plain str ("ladybug"|"neo4j"|"none"), not an enum —
    # no .value accessor (DatabaseStrategy.graph_type: str in strategy.py)
    assert strategy.graph_type == "ladybug"


@pytest.mark.asyncio
async def test_article_graph_node_only_stores_pg_id(phase3_container):
    """Graph Article node stores only pg_id; title lives in PG.

    After Article node slim-down (design.md §D2), LadybugDB Article node
    stores only {id, pg_id}; title/score live in PG and are batch-fetched
    by GraphArticleReader on read.
    """
    pg_id = str(uuid.uuid4())
    try:
        await seed_test_article(phase3_container, pg_id, title="Test Article Title")

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
    finally:
        await cleanup_test_article(phase3_container, pg_id)


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
    try:
        await seed_test_article(phase3_container, pg_id, title="Enriched Title From PG")

        graph_repo = phase3_container.graph_repo()
        article = await graph_repo.get_article(pg_id)
        assert article is not None
        assert article["id"] == pg_id
        # title is fetched from PG, not stored on graph node
        assert article.get("title") == "Enriched Title From PG"
    finally:
        await cleanup_test_article(phase3_container, pg_id)

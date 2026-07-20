# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared fixtures + helpers for tests/integration/api/ module.

Centralizes:
- FakeLLMClient / FakePromptLoader: stub LLM + prompt loader for integration
  tests (project hook forbids MagicMock in integration tests). Used by
  test_briefings_narrative_e2e.py, test_hybrid_mode_pg_ladybug.py,
  test_hybrid_mode_duckdb_neo4j.py.
- _seed_test_article: insert a minimal ArticleCore row + slim Article graph
  node ({id, pg_id} per design.md §D2). Used by hybrid mode tests.
- require_localhost_dsn: safety guard preventing integration tests from
  running against non-localhost DB DSN (avoids accidental prod pollution).
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from sqlalchemy import text

from core.db import ArticleCore
from core.observability import get_logger

log = get_logger(__name__)


class FakeLLMClient:
    """Real Python class stub replacing LLMClient for integration tests.

    Project hook forbids MagicMock in integration tests (Rule: integration
    tests MUST use real services). This stub is a concrete class implementing
    the LLMClient interface (call_at method). The stub is never invoked
    during factory construction / search engine init — only container
    properties wire it as a dependency. The stub's call_at method raises
    AssertionError if ever called (defensive — factory / search(use_llm=False)
    should NOT trigger LLM calls).
    """

    async def call_at(self, call_point: Any, payload: Any) -> str:
        raise AssertionError(
            "FakeLLMClient.call_at should never be called during factory "
            "construction or search(use_llm=False) — wiring only, no LLM invocation."
        )


class FakePromptLoader:
    """Real Python class stub replacing PromptLoader for integration tests.

    Avoids file IO dependency on config/prompts directory. Implements the
    PromptLoader interface (get + get_version methods).
    """

    def get(self, name: str, section: str | None = None) -> str:
        return f"fake {name} prompt"

    def get_version(self, name: str) -> str:
        return "0.0.0-fake"


def require_localhost_dsn() -> bool:
    """Safety guard: return True if all configured DB DSNs point to localhost.

    Hybrid mode integration tests write real data into PG / Neo4j. This
    guard prevents accidental runs against production hosts by checking
    that WEAVER_POSTGRES__DSN (if set) contains localhost / 127.0.0.1.

    Returns:
        True if safe to proceed (localhost or unset); False if non-localhost
        host detected (tests should skip).
    """
    dsn = os.getenv("WEAVER_POSTGRES__DSN", "")
    if not dsn:
        return True  # DuckDB fallback path, no remote DB
    unsafe_markers = ("prod", "staging", "remote", ".com", ".org", ".net")
    if any(marker in dsn.lower() for marker in unsafe_markers):
        return False
    # Unknown host — be conservative and block (only allow explicit localhost)
    return "localhost" in dsn or "127.0.0.1" in dsn


async def seed_test_article(container, pg_id: str, title: str) -> None:
    """Insert a minimal article into the relational DB and create a slim
    Article graph node.

    The graph node stores only {id, pg_id} per design.md §D2 — title lives
    in the relational DB (PG or DuckDB) and is batch-fetched by
    GraphArticleReader on read.

    Uses CREATE (not MERGE) — LadybugDB (Kùzu) requires PRIMARY KEY `id`
    at creation time; MERGE internally CREATEs when the node doesn't exist,
    but the MERGE pattern only specifies pg_id, triggering BinderException.
    Tests use unique UUIDs so CREATE has no collision risk. Works for
    Neo4j too (CREATE with explicit id is standard Cypher).

    Args:
        container: Initialized Container with relational_pool + graph_pool.
        pg_id: UUID string for the article (used as PG/DuckDB primary key
            and graph node pg_id property).
        title: Article title (stored in relational DB only).
    """
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
    await graph_pool.execute_query(
        """
        CREATE (a:Article {
            id: $id,
            pg_id: $pg_id
        })
        RETURN a.pg_id AS pg_id
        """,
        {"id": str(uuid.uuid4()), "pg_id": pg_id},
    )


async def cleanup_test_article(container, pg_id: str) -> None:
    """Clean up a seeded article from both relational DB and graph.

    Called in fixture teardown to avoid test data accumulation across
    repeated test runs. Safe to call even if the article was never created
    (DELETE / DETACH DELETE is idempotent on missing rows).

    Args:
        container: Initialized Container.
        pg_id: UUID string of the article to delete.
    """
    # Delete from graph first (FK-like: graph node references pg_id only)
    graph_pool = container.graph_pool()
    try:
        await graph_pool.execute_query(
            "MATCH (a:Article {pg_id: $pg_id}) DETACH DELETE a",
            {"pg_id": pg_id},
        )
    except Exception as exc:
        log.warning("cleanup_graph_article_failed", error=str(exc), pg_id=pg_id)

    # Delete from relational DB
    pool = container.relational_pool()
    try:
        async with pool.session() as session:
            await session.execute(
                text("DELETE FROM articles_core WHERE id = :id"),
                {"id": uuid.UUID(pg_id)},
            )
            await session.commit()
    except Exception as exc:
        log.warning("cleanup_relational_article_failed", error=str(exc), pg_id=pg_id)

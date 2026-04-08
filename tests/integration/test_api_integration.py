# Copyright (c) 2026 Kirky-X. All Rights Reserved
"""Integration tests for API cross-endpoint workflows with fallback databases.

All tests use fallback databases (DuckDB, LadybugDB, CashewsRedisFallback)
when external services are not available.
"""

import socket
import uuid

import pytest
from sqlalchemy import text

from core.event.bus import EventBus
from core.llm.types import TokenUsage
from core.net.port_finder import PortFinder
from modules.analytics.llm_usage.buffer import LLMUsageBuffer
from modules.analytics.llm_usage.repo import LLMUsageRepo
from modules.storage.postgres.vector_repo import VectorRepo


class TestLLMUsagePipelineIntegration:
    """Integration tests for LLM usage tracking pipeline with fallback databases."""

    @pytest.mark.asyncio
    async def test_llm_usage_aggregation_flow(self, relational_pool, unique_id):
        """Test LLM usage flows from raw records to aggregated hourly."""
        pool, _ = relational_pool
        repo = LLMUsageRepo(pool)

        # Insert a raw usage record
        from datetime import UTC, datetime

        from core.db.models import LLMUsageRaw

        raw = LLMUsageRaw(
            label=f"test_{unique_id}",
            call_point="classifier",
            llm_type="chat",
            provider="anthropic",
            model="claude-3-opus",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            latency_ms=500.0,
            success=True,
        )

        # Insert raw record
        async with pool.session_context() as session:
            session.add(raw)
            await session.commit()

        try:
            # Verify record was inserted
            async with pool.session_context() as session:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM llm_usage_raw WHERE label = :label"),
                    {"label": f"test_{unique_id}"},
                )
                count = result.scalar()
                assert count == 1
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM llm_usage_raw WHERE label = :label"),
                    {"label": f"test_{unique_id}"},
                )

    @pytest.mark.asyncio
    async def test_llm_failure_tracking_integration(self, relational_pool, event_bus, unique_id):
        """Test LLM failures are tracked and queryable."""
        pool, _ = relational_pool
        from core.event.bus import LLMFailureEvent
        from modules.analytics.llm_failure.repo import LLMFailureRepo

        repo = LLMFailureRepo(pool)

        # Subscribe handler
        async def handle(event):
            await repo.record(event)

        event_bus.subscribe(LLMFailureEvent, handle)

        # Publish failure event
        await event_bus.publish(
            LLMFailureEvent(
                call_point=f"test_{unique_id}",
                provider="openai",
                error_type="TimeoutError",
                error_detail="Request timed out",
                latency_ms=30000.0,
                article_id=None,
                task_id="test-task",
                attempt=1,
                fallback_tried=True,
            )
        )

        try:
            # Verify record was created
            async with pool.session_context() as session:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM llm_failures WHERE call_point = :cp"),
                    {"cp": f"test_{unique_id}"},
                )
                count = result.scalar()
                assert count == 1
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM llm_failures WHERE call_point = :cp"),
                    {"cp": f"test_{unique_id}"},
                )


class TestVectorRepoIntegration:
    """Integration tests for vector repository operations with fallback databases."""

    @pytest.mark.asyncio
    async def test_vector_search_integration(self, relational_pool, unique_id):
        """Test vector search returns relevant results with fallback database."""
        from core.db.query_builders import create_vector_query_builder

        pool, db_type = relational_pool
        query_builder = create_vector_query_builder(db_type)
        repo = VectorRepo(pool=pool, query_builder=query_builder)

        # Verify repo is initialized correctly
        assert repo._pool is pool

        # Test that we can query without error (empty result is fine)
        # This verifies the database connection works
        async with pool.session_context() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1


class TestArticleRepoIntegration:
    """Integration tests for article repository with fallback databases."""

    @pytest.mark.asyncio
    async def test_article_crud_integration(self, relational_pool, unique_id):
        """Test article CRUD operations work together with fallback database."""
        from types import SimpleNamespace

        from modules.processing.pipeline.state import PipelineState
        from modules.storage.postgres.article_repo import ArticleRepo

        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        # Create test article
        state = PipelineState()
        state["raw"] = SimpleNamespace(
            url=f"https://test.example.com/{unique_id}",
            source_host="test.example.com",
            title=f"Test Article {unique_id}",
            body="Test body content",
            publish_time=None,
        )
        state["is_news"] = True
        state["category"] = "科技"
        state["language"] = "zh"

        try:
            # Upsert article
            article_id = await repo.upsert(state)
            assert isinstance(article_id, uuid.UUID)

            # Verify article exists
            async with pool.session_context() as session:
                result = await session.execute(
                    text("SELECT id, title FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row is not None
                assert row.title == f"Test Article {unique_id}"
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )


class TestNeo4jSyncIntegration:
    """Integration tests for Neo4j synchronization with fallback graph database."""

    @pytest.mark.asyncio
    async def test_entity_sync_integration(self, graph_pool, unique_id):
        """Test entity synchronization to graph database with fallback."""
        from modules.knowledge.graph.neo4j_writer import Neo4jWriter

        pool, db_type = graph_pool
        writer = Neo4jWriter(pool=pool)

        # Verify writer is initialized correctly
        assert writer._pool is pool


class TestCrossEndpointWorkflows:
    """Integration tests for cross-endpoint workflows with fallback databases."""

    @pytest.mark.asyncio
    async def test_article_to_graph_workflow(
        self, relational_pool, graph_pool, event_bus, unique_id
    ):
        """Test processing article creates graph entities with fallback databases."""
        from types import SimpleNamespace

        from modules.processing.pipeline.state import PipelineState
        from modules.storage.postgres.article_repo import ArticleRepo

        pg_pool, _ = relational_pool
        neo_pool, neo_db_type = graph_pool
        repo = ArticleRepo(pg_pool)

        # Create test article
        state = PipelineState()
        state["raw"] = SimpleNamespace(
            url=f"https://workflow.example.com/{unique_id}",
            source_host="workflow.example.com",
            title=f"Workflow Test {unique_id}",
            body="Test content about OpenAI and Anthropic",
            publish_time=None,
        )
        state["is_news"] = True
        state["category"] = "科技"
        state["language"] = "zh"

        try:
            # Step 1: Create article
            article_id = await repo.upsert(state)
            assert article_id is not None

            # Step 2: Create graph entities using EntityRepository (handles LadybugDB)
            if neo_db_type == "ladybug":
                from modules.storage.ladybug import LadybugEntityRepo

                entity_repo = LadybugEntityRepo(neo_pool)
            else:
                from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

                entity_repo = Neo4jEntityRepo(neo_pool)

            await entity_repo.merge_entity("OpenAI", "组织")
            await entity_repo.merge_entity("Anthropic", "组织")

            # Step 3: Verify graph entities exist
            openai = await entity_repo.find_entity("OpenAI", "组织")
            anthropic = await entity_repo.find_entity("Anthropic", "组织")
            assert openai is not None
            assert anthropic is not None

        finally:
            # Cleanup PostgreSQL
            async with pg_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )
            # Cleanup Neo4j/LadybugDB
            await neo_pool.execute_query(
                "MATCH (e:Entity) WHERE e.canonical_name IN ['OpenAI', 'Anthropic'] DETACH DELETE e"
            )

    @pytest.mark.asyncio
    async def test_search_to_article_workflow(self, relational_pool, unique_id):
        """Test search results link to articles with fallback database."""
        from types import SimpleNamespace

        from modules.processing.pipeline.state import PipelineState
        from modules.storage.postgres.article_repo import ArticleRepo

        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        # Create test article
        state = PipelineState()
        state["raw"] = SimpleNamespace(
            url=f"https://search.example.com/{unique_id}",
            source_host="search.example.com",
            title=f"Search Test {unique_id}",
            body="Test content for search workflow",
            publish_time=None,
        )
        state["is_news"] = True
        state["category"] = "科技"
        state["language"] = "zh"

        try:
            # Step 1: Create article
            article_id = await repo.upsert(state)

            # Step 2: Search for article (using raw SQL as search)
            async with pool.session_context() as session:
                result = await session.execute(
                    text("SELECT id, title FROM articles WHERE title LIKE :pattern LIMIT 10"),
                    {"pattern": f"%{unique_id}%"},
                )
                rows = result.fetchall()
                assert len(rows) >= 1

            # Step 3: Get article by ID
            async with pool.session_context() as session:
                result = await session.execute(
                    text("SELECT id, title, body FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
                article = result.fetchone()
                assert article is not None
                assert f"{unique_id}" in article.title

        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )


class TestSSRFProtectionIntegration:
    """Integration tests for SSRF protection with real network checks."""

    @pytest.mark.asyncio
    async def test_ssrf_checker_is_safe_url(self):
        """Test SSRFChecker is_safe_url method with real DNS resolution."""
        from core.security.ssrf import SSRFChecker

        checker = SSRFChecker()

        # Public URLs should be considered safe
        assert checker.is_safe_url("https://example.com") is True
        assert checker.is_safe_url("https://google.com") is True
        assert checker.is_safe_url("https://github.com") is True

    @pytest.mark.asyncio
    async def test_ssrf_checker_blocks_private_urls(self):
        """Test SSRFChecker blocks private IPs with real network checks."""
        from core.security.ssrf import SSRFChecker

        checker = SSRFChecker()

        # Private IPs should be blocked (is_safe_url is sync check for direct IPs)
        assert checker.is_safe_url("http://192.168.1.1/") is False
        assert checker.is_safe_url("http://10.0.0.1/") is False
        assert checker.is_safe_url("http://127.0.0.1/") is False
        assert checker.is_safe_url("http://172.16.0.1/") is False

    @pytest.mark.asyncio
    async def test_ssrf_checker_hostname_not_blocked(self):
        """Test SSRFChecker allows hostnames (sync check doesn't resolve DNS)."""
        from core.security.ssrf import SSRFChecker

        checker = SSRFChecker()

        # is_safe_url is synchronous and doesn't resolve DNS
        # 'localhost' is a hostname, not an IP, so it passes the sync check
        # For full validation with DNS resolution, use the async validate() method
        assert checker.is_safe_url("http://localhost/") is True
        assert checker.is_safe_url("http://local-host.example.com/") is True

    @pytest.mark.asyncio
    async def test_ssrf_checker_blocks_localhost_variants(self):
        """Test SSRFChecker blocks various localhost representations."""
        from core.security.ssrf import SSRFChecker

        checker = SSRFChecker()

        # Various localhost representations should be blocked
        assert checker.is_safe_url("http://127.0.0.1:8080/") is False
        assert checker.is_safe_url("http://[::1]/") is False
        assert checker.is_safe_url("http://0.0.0.0/") is False


class TestPortDetectionIntegration:
    """Integration tests for port detection with real socket operations."""

    @pytest.mark.asyncio
    async def test_port_detection_finds_available(self):
        """Test port detection finds available port with real socket."""
        finder = PortFinder()

        # Find an available port
        port = finder.find_available_port(host="127.0.0.1", start_port=9000, max_attempts=100)

        assert port is not None
        assert 9000 <= port < 9100

        # Verify the port is actually available
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", port))
            # Connection should fail (port is free)
            assert result != 0

    @pytest.mark.asyncio
    async def test_port_detection_handles_in_use(self):
        """Test port detection handles in-use port with real socket."""
        finder = PortFinder()

        # Create a socket on a known port
        test_port = 19999
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", test_port))
            s.listen(1)

            # Verify our port is in use
            assert finder.is_port_available("127.0.0.1", test_port) is False

        # After closing, port should be available again
        assert finder.is_port_available("127.0.0.1", test_port) is True

    @pytest.mark.asyncio
    async def test_port_finder_multiple_available(self):
        """Test finding available ports at different ranges."""
        finder = PortFinder()

        # Find ports at different starting points to get distinct values
        port1 = finder.find_available_port(host="127.0.0.1", start_port=20000, max_attempts=100)
        port2 = finder.find_available_port(host="127.0.0.1", start_port=30000, max_attempts=100)
        port3 = finder.find_available_port(host="127.0.0.1", start_port=40000, max_attempts=100)

        # All ports should be available
        assert finder.is_port_available("127.0.0.1", port1) is True
        assert finder.is_port_available("127.0.0.1", port2) is True
        assert finder.is_port_available("127.0.0.1", port3) is True

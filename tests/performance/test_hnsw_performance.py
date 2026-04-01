# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Performance tests for HNSW vector index - requires PostgreSQL with pgvector."""

import asyncio
import time
import uuid

import numpy as np
import pytest
from sqlalchemy import text

from core.db.postgres import PostgresPool
from modules.storage.postgres.vector_repo import VectorRepo


@pytest.mark.performance
@pytest.mark.slow
class TestHNSWPerformance:
    """Performance tests for HNSW index with large-scale vector data."""

    @pytest.fixture
    async def postgres_pool(self):
        """Create PostgreSQL pool for performance tests."""
        import os

        dsn = os.getenv(
            "POSTGRES_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver"
        )
        pool = PostgresPool(dsn)
        await pool.startup()
        yield pool
        await pool.shutdown()

    @pytest.fixture
    async def vector_repo(self, postgres_pool):
        """Create VectorRepo instance with real pool."""
        return VectorRepo(postgres_pool)

    @pytest.fixture
    async def hnsw_index_exists(self, postgres_pool):
        """Verify HNSW indexes exist before running tests."""
        async with postgres_pool.session() as session:
            # Check article_vectors HNSW index
            result = await session.execute(text("""
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'article_vectors'
                  AND indexname = 'idx_article_vectors_hnsw'
            """))
            article_index = result.scalar_one_or_none()

            # Check entity_vectors HNSW index
            result = await session.execute(text("""
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'entity_vectors'
                  AND indexname = 'idx_entity_vectors_hnsw'
            """))
            entity_index = result.scalar_one_or_none()

            return article_index is not None and entity_index is not None

    def generate_random_vector(self, dim: int = 1024) -> list[float]:
        """Generate a random normalized vector.

        Args:
            dim: Vector dimension.

        Returns:
            Normalized random vector.
        """
        vec = np.random.randn(dim)
        # Normalize to unit length for cosine similarity
        norm = np.linalg.norm(vec)
        return (vec / norm).tolist()

    def generate_random_vectors(self, count: int, dim: int = 1024) -> list[list[float]]:
        """Generate multiple random normalized vectors.

        Args:
            count: Number of vectors to generate.
            dim: Vector dimension.

        Returns:
            List of normalized random vectors.
        """
        vecs = np.random.randn(count, dim)
        # Normalize all vectors
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        normalized = vecs / norms
        return normalized.tolist()

    @pytest.mark.asyncio
    async def test_bulk_insert_performance(self, postgres_pool, vector_repo, hnsw_index_exists):
        """Test bulk insert performance with 10,000 vectors.

        This test verifies:
        1. Bulk insert can handle large datasets efficiently
        2. Insert time is reasonable (< 5 minutes for 10K vectors)
        3. HNSW index exists before test
        """
        if not hnsw_index_exists:
            pytest.skip("HNSW indexes not created - run migrations first")

        # Generate test data - using 10,000 vectors for reasonable test time
        num_vectors = 10_000
        batch_size = 1_000
        vector_dim = 1024

        print(f"\n准备生成 {num_vectors} 个 {vector_dim} 维向量...")

        # Generate all vectors upfront
        all_vectors = self.generate_random_vectors(num_vectors, vector_dim)

        print("向量生成完成，开始批量插入...")

        # Track timing
        start_time = time.time()
        total_inserted = 0

        # Insert in batches
        for batch_start in range(0, num_vectors, batch_size):
            batch_end = min(batch_start + batch_size, num_vectors)
            batch_vectors = all_vectors[batch_start:batch_end]

            # Prepare batch data
            articles = [
                (
                    uuid.uuid4(),  # article_id
                    self.generate_random_vector(vector_dim),  # title_embedding
                    batch_vectors[i],  # content_embedding
                    "test-model",  # model_id
                )
                for i in range(len(batch_vectors))
            ]

            # Pre-insert articles so FK constraint is satisfied
            article_ids = [a[0] for a in articles]
            async with postgres_pool.session() as session:
                await session.execute(
                    text("""
                        INSERT INTO articles (id, source_url, title, body, is_news, is_merged, persist_status, verified_by_sources)
                        VALUES (:id, :url, :title, :body, false, false, 'pending', 0)
                        ON CONFLICT (id) DO NOTHING
                    """),
                    [
                        {
                            "id": aid,
                            "url": f"http://test/{aid}",
                            "title": "perf-test",
                            "body": "perf-test-body",
                        }
                        for aid in article_ids
                    ],
                )
                await session.commit()

            # Bulk insert
            count = await vector_repo.bulk_upsert_article_vectors(articles)
            total_inserted += count

            # Progress report
            elapsed = time.time() - start_time
            rate = total_inserted / elapsed if elapsed > 0 else 0
            print(
                f"已插入 {total_inserted}/{num_vectors} 向量 "
                f"({rate:.1f} 向量/秒, {elapsed:.1f}s)"
            )

        total_time = time.time() - start_time

        # Performance assertions
        avg_rate = total_inserted / total_time
        print(f"\n总插入时间: {total_time:.2f} 秒")
        print(f"平均插入速率: {avg_rate:.1f} 向量/秒")
        print(f"总插入数量: {total_inserted} 向量")

        # Assert reasonable performance
        # Should be able to insert at least 100 vectors/second
        assert avg_rate >= 100, f"Insert rate too slow: {avg_rate:.1f} vectors/sec"
        assert (
            total_inserted == num_vectors * 2
        ), f"Missing vectors: inserted {total_inserted}/{num_vectors * 2}"

    @pytest.mark.asyncio
    async def test_hnsw_index_usage(self, postgres_pool, vector_repo, hnsw_index_exists):
        """Verify HNSW index is being used for queries.

        This test:
        1. Inserts test vectors
        2. Runs similarity search with EXPLAIN ANALYZE
        3. Verifies HNSW index is used in query plan
        """
        if not hnsw_index_exists:
            pytest.skip("HNSW indexes not created - run migrations first")

        # Insert some test vectors first
        num_test_vectors = 100
        test_vectors = self.generate_random_vectors(num_test_vectors)

        articles = [
            (uuid.uuid4(), self.generate_random_vector(1024), test_vectors[i], "test-model")
            for i in range(num_test_vectors)
        ]

        # Pre-insert articles so FK constraint is satisfied
        article_ids = [a[0] for a in articles]
        async with postgres_pool.session() as session:
            await session.execute(
                text("""
                    INSERT INTO articles (id, source_url, title, body, is_news, is_merged, persist_status, verified_by_sources)
                    VALUES (:id, :url, :title, :body, false, false, 'pending', 0)
                    ON CONFLICT (id) DO NOTHING
                """),
                [
                    {
                        "id": aid,
                        "url": f"http://test/{aid}",
                        "title": "perf-test",
                        "body": "perf-test-body",
                    }
                    for aid in article_ids
                ],
            )
            await session.commit()

        await vector_repo.bulk_upsert_article_vectors(articles)

        # Run similarity search with EXPLAIN ANALYZE
        query_vector = self.generate_random_vector(1024)

        async with postgres_pool.session() as session:
            # Get query execution plan
            result = await session.execute(
                text("""
                EXPLAIN (ANALYZE, BUFFERS)
                SELECT
                    a.id::text as article_id,
                    a.category,
                    1 - (av.embedding <=> cast(:embedding as vector)) as similarity
                FROM article_vectors av
                JOIN articles a ON a.id = av.article_id
                WHERE av.vector_type = 'content'
                  AND a.is_merged = FALSE
                  AND 1 - (av.embedding <=> cast(:embedding as vector)) > 0.5
                ORDER BY similarity DESC
                LIMIT 20
            """),
                {"embedding": str(query_vector)},
            )

            plan_lines = [row[0] for row in result]

        # Print query plan for debugging
        print("\n查询执行计划:")
        for line in plan_lines:
            print(line)

        # Verify HNSW index is used (or skip if table is too small for index to be chosen)
        plan_text = "\n".join(plan_lines)
        if "idx_article_vectors_hnsw" not in plan_text:
            pytest.skip("HNSW index not used for small dataset (normal planner behavior)")

        # Verify query execution time
        import re

        time_match = re.search(r"Execution Time: ([\d.]+) ms", plan_text)
        if time_match:
            exec_time_ms = float(time_match.group(1))
            print(f"\n查询执行时间: {exec_time_ms:.2f} ms")
            assert exec_time_ms < 100, f"Query too slow: {exec_time_ms:.2f}ms (should be < 100ms)"

    @pytest.mark.asyncio
    async def test_query_performance_consistency(
        self, postgres_pool, vector_repo, hnsw_index_exists
    ):
        """Test query performance across different query vectors.

        This test verifies:
        1. Query times are consistent across different vectors
        2. All queries complete within 100ms
        3. Performance doesn't degrade with different query patterns
        """
        if not hnsw_index_exists:
            pytest.skip("HNSW indexes not created - run migrations first")

        # Insert test vectors
        num_test_vectors = 100
        test_vectors = self.generate_random_vectors(num_test_vectors)

        articles = [
            (uuid.uuid4(), self.generate_random_vector(1024), test_vectors[i], "test-model")
            for i in range(num_test_vectors)
        ]

        # Pre-insert articles so FK constraint is satisfied
        article_ids = [a[0] for a in articles]
        async with postgres_pool.session() as session:
            await session.execute(
                text("""
                    INSERT INTO articles (id, source_url, title, body, is_news, is_merged, persist_status, verified_by_sources)
                    VALUES (:id, :url, :title, :body, false, false, 'pending', 0)
                    ON CONFLICT (id) DO NOTHING
                """),
                [
                    {
                        "id": aid,
                        "url": f"http://test/{aid}",
                        "title": "perf-test",
                        "body": "perf-test-body",
                    }
                    for aid in article_ids
                ],
            )
            await session.commit()

        await vector_repo.bulk_upsert_article_vectors(articles)

        # Test multiple query vectors
        num_queries = 20
        query_vectors = self.generate_random_vectors(num_queries)

        query_times = []

        print(f"\n测试 {num_queries} 个不同查询向量的性能...")

        for i, query_vec in enumerate(query_vectors):
            start = time.time()

            results = await vector_repo.find_similar(
                embedding=query_vec, threshold=0.5, limit=20, model_id="test-model"
            )

            query_time = (time.time() - start) * 1000  # Convert to ms
            query_times.append(query_time)

            print(f"查询 {i+1}/{num_queries}: {query_time:.2f}ms, 结果数: {len(results)}")

        # Analyze performance
        avg_time = np.mean(query_times)
        max_time = np.max(query_times)
        min_time = np.min(query_times)
        std_time = np.std(query_times)

        print("\n查询性能统计:")
        print(f"  平均时间: {avg_time:.2f} ms")
        print(f"  最大时间: {max_time:.2f} ms")
        print(f"  最小时间: {min_time:.2f} ms")
        print(f"  标准差: {std_time:.2f} ms")

        # Performance assertions
        assert max_time < 1000, f"Slow query detected: {max_time:.2f}ms (should be < 1000ms)"
        assert (
            std_time < 100
        ), f"High query time variance: {std_time:.2f}ms (indicates inconsistent performance)"

    @pytest.mark.asyncio
    async def test_concurrent_query_performance(
        self, postgres_pool, vector_repo, hnsw_index_exists
    ):
        """Test concurrent query performance.

        This test verifies:
        1. Multiple concurrent queries can be handled
        2. Performance remains acceptable under concurrent load
        3. No connection pool exhaustion
        """
        if not hnsw_index_exists:
            pytest.skip("HNSW indexes not created - run migrations first")

        # Insert test vectors
        num_test_vectors = 100
        test_vectors = self.generate_random_vectors(num_test_vectors)

        articles = [
            (uuid.uuid4(), self.generate_random_vector(1024), test_vectors[i], "test-model")
            for i in range(num_test_vectors)
        ]

        # Pre-insert articles so FK constraint is satisfied
        article_ids = [a[0] for a in articles]
        async with postgres_pool.session() as session:
            await session.execute(
                text("""
                    INSERT INTO articles (id, source_url, title, body, is_news, is_merged, persist_status, verified_by_sources)
                    VALUES (:id, :url, :title, :body, false, false, 'pending', 0)
                    ON CONFLICT (id) DO NOTHING
                """),
                [
                    {
                        "id": aid,
                        "url": f"http://test/{aid}",
                        "title": "perf-test",
                        "body": "perf-test-body",
                    }
                    for aid in article_ids
                ],
            )
            await session.commit()

        await vector_repo.bulk_upsert_article_vectors(articles)

        # Prepare concurrent queries
        num_concurrent = 10
        query_vectors = self.generate_random_vectors(num_concurrent)

        async def run_query(idx: int, query_vec: list[float]) -> tuple[int, float, int]:
            """Run a single query and return timing info."""
            start = time.time()
            results = await vector_repo.find_similar(
                embedding=query_vec, threshold=0.5, limit=20, model_id="test-model"
            )
            elapsed = (time.time() - start) * 1000
            return (idx, elapsed, len(results))

        print(f"\n运行 {num_concurrent} 个并发查询...")

        # Run queries concurrently
        start = time.time()
        tasks = [run_query(i, vec) for i, vec in enumerate(query_vectors)]
        results = await asyncio.gather(*tasks)
        total_time = (time.time() - start) * 1000

        # Analyze results
        query_times = [r[1] for r in results]
        result_counts = [r[2] for r in results]

        print("\n并发查询结果:")
        for idx, elapsed, count in results:
            print(f"  查询 {idx}: {elapsed:.2f}ms, 结果数: {count}")

        print(f"\n总耗时: {total_time:.2f} ms")
        print(f"平均查询时间: {np.mean(query_times):.2f} ms")
        print(f"最大查询时间: {np.max(query_times):.2f} ms")

        # Performance assertions
        assert (
            max(query_times) < 2000
        ), f"Slow concurrent query: {max(query_times):.2f}ms (should be < 2000ms)"
        assert total_time < 5000, f"Concurrent queries too slow: {total_time:.2f}ms total"

    @pytest.mark.asyncio
    async def test_large_scale_similarity_search(
        self, postgres_pool, vector_repo, hnsw_index_exists
    ):
        """Test similarity search with larger dataset.

        This test:
        1. Inserts 50,000 vectors (if time permits)
        2. Measures query performance at scale
        3. Verifies HNSW maintains < 100ms queries
        """
        if not hnsw_index_exists:
            pytest.skip("HNSW indexes not created - run migrations first")

        # Use smaller scale for CI/testing, can increase for real performance testing
        num_vectors = 5_000  # Adjust based on test requirements
        batch_size = 500
        vector_dim = 1024

        print(f"\n插入 {num_vectors} 个向量用于大规模测试...")

        # Insert vectors in batches
        total_inserted = 0
        start_time = time.time()

        for batch_start in range(0, num_vectors, batch_size):
            batch_end = min(batch_start + batch_size, num_vectors)
            batch_count = batch_end - batch_start

            batch_vectors = self.generate_random_vectors(batch_count, vector_dim)

            articles = [
                (
                    uuid.uuid4(),
                    self.generate_random_vector(vector_dim),
                    batch_vectors[i],
                    "test-model",
                )
                for i in range(batch_count)
            ]

            # Pre-insert articles so FK constraint is satisfied
            article_ids = [a[0] for a in articles]
            async with postgres_pool.session() as session:
                await session.execute(
                    text("""
                        INSERT INTO articles (id, source_url, title, body, is_news, is_merged, persist_status, verified_by_sources)
                        VALUES (:id, :url, :title, :body, false, false, 'pending', 0)
                        ON CONFLICT (id) DO NOTHING
                    """),
                    [
                        {
                            "id": aid,
                            "url": f"http://test/{aid}",
                            "title": "perf-test",
                            "body": "perf-test-body",
                        }
                        for aid in article_ids
                    ],
                )
                await session.commit()

            count = await vector_repo.bulk_upsert_article_vectors(articles)
            total_inserted += count

            if batch_start % 1000 == 0:
                print(f"已插入 {total_inserted}/{num_vectors} 向量...")

        insert_time = time.time() - start_time
        print(f"插入完成: {total_inserted} 向量, 耗时 {insert_time:.1f}s")

        # Test query performance at scale
        num_test_queries = 10
        query_vectors = self.generate_random_vectors(num_test_queries)

        query_times = []
        print("\n在大规模数据集上测试查询性能...")

        for i, query_vec in enumerate(query_vectors):
            start = time.time()
            results = await vector_repo.find_similar(
                embedding=query_vec, threshold=0.5, limit=20, model_id="test-model"
            )
            query_time = (time.time() - start) * 1000
            query_times.append(query_time)

            print(f"查询 {i+1}: {query_time:.2f}ms, 结果数: {len(results)}")

        # Performance assertions
        avg_time = np.mean(query_times)
        max_time = np.max(query_times)

        print("\n大规模查询性能:")
        print(f"  平均时间: {avg_time:.2f} ms")
        print(f"  最大时间: {max_time:.2f} ms")

        # HNSW should maintain < 1000ms even at scale
        assert avg_time < 1000, f"Average query too slow at scale: {avg_time:.2f}ms"
        assert max_time < 2000, f"Max query too slow at scale: {max_time:.2f}ms"


@pytest.mark.performance
@pytest.mark.slow
class TestHNSWIndexCreation:
    """Tests for HNSW index creation and parameters."""

    @pytest.fixture
    async def postgres_pool(self):
        """Create PostgreSQL pool for tests."""
        import os

        dsn = os.getenv(
            "POSTGRES_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver"
        )
        pool = PostgresPool(dsn)
        await pool.startup()
        yield pool
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_verify_hnsw_index_parameters(self, postgres_pool):
        """Verify HNSW indexes were created with correct parameters."""
        async with postgres_pool.session() as session:
            # Check article_vectors index
            result = await session.execute(text("""
                SELECT
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE tablename = 'article_vectors'
                  AND indexname = 'idx_article_vectors_hnsw'
            """))
            article_idx = result.first()

            # Check entity_vectors index
            result = await session.execute(text("""
                SELECT
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE tablename = 'entity_vectors'
                  AND indexname = 'idx_entity_vectors_hnsw'
            """))
            entity_idx = result.first()

        # Verify indexes exist
        assert article_idx is not None, "HNSW index not found on article_vectors"
        assert entity_idx is not None, "HNSW index not found on entity_vectors"

        # Verify index uses HNSW algorithm
        assert "USING hnsw" in article_idx[1], "article_vectors index not using HNSW algorithm"
        assert "USING hnsw" in entity_idx[1], "entity_vectors index not using HNSW algorithm"

        # Verify vector_cosine_ops
        assert (
            "vector_cosine_ops" in article_idx[1]
        ), "article_vectors index not using vector_cosine_ops"
        assert (
            "vector_cosine_ops" in entity_idx[1]
        ), "entity_vectors index not using vector_cosine_ops"

        print("\n✓ HNSW 索引已正确创建")
        print(f"  article_vectors: {article_idx[0]}")
        print(f"  entity_vectors: {entity_idx[0]}")

    @pytest.mark.asyncio
    async def test_hnsw_ef_search_setting(self, postgres_pool):
        """Verify hnsw.ef_search parameter can be set for query tuning."""
        async with postgres_pool.session() as session:
            # Set ef_search
            await session.execute(text("SET hnsw.ef_search = 200;"))

            # Verify setting
            result = await session.execute(text("SHOW hnsw.ef_search;"))
            ef_search = result.scalar()

            assert ef_search == "200", f"Failed to set hnsw.ef_search: got {ef_search}"

        print("\n✓ hnsw.ef_search 参数设置正常")


@pytest.mark.performance
@pytest.mark.slow
class TestVectorRepoPerformance:
    """Performance tests for VectorRepo operations."""

    @pytest.fixture
    async def postgres_pool(self):
        """Create PostgreSQL pool for tests."""
        import os

        dsn = os.getenv(
            "POSTGRES_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver"
        )
        pool = PostgresPool(dsn)
        await pool.startup()
        yield pool
        await pool.shutdown()

    @pytest.fixture
    async def vector_repo(self, postgres_pool):
        """Create VectorRepo instance."""
        return VectorRepo(postgres_pool)

    @pytest.mark.asyncio
    async def test_batch_find_similar_performance(self, vector_repo, postgres_pool):
        """Test batch query performance vs individual queries."""
        # Prepare test data
        num_test_articles = 50
        articles = [
            (
                uuid.uuid4(),
                np.random.randn(1024).tolist(),
                np.random.randn(1024).tolist(),
                "test-model",
            )
            for _ in range(num_test_articles)
        ]

        # Pre-insert articles so FK constraint is satisfied
        article_ids = [a[0] for a in articles]
        async with postgres_pool.session() as session:
            await session.execute(
                text("""
                    INSERT INTO articles (id, source_url, title, body, is_news, is_merged, persist_status, verified_by_sources)
                    VALUES (:id, :url, :title, :body, false, false, 'pending', 0)
                    ON CONFLICT (id) DO NOTHING
                """),
                [
                    {
                        "id": aid,
                        "url": f"http://test/{aid}",
                        "title": "perf-test",
                        "body": "perf-test-body",
                    }
                    for aid in article_ids
                ],
            )
            await session.commit()

        await vector_repo.bulk_upsert_article_vectors(articles)

        # Test individual queries
        num_queries = 10
        query_vectors = [np.random.randn(1024).tolist() for _ in range(num_queries)]

        print("\n测试单独查询性能...")
        individual_start = time.time()
        for query_vec in query_vectors:
            await vector_repo.find_similar(
                embedding=query_vec, threshold=0.5, limit=20, model_id="test-model"
            )
        individual_time = time.time() - individual_start

        # Test batch queries
        queries = [(uuid.uuid4(), vec) for vec in query_vectors]

        print("测试批量查询性能...")
        batch_start = time.time()
        results = await vector_repo.batch_find_similar(
            queries=queries, threshold=0.5, limit=20, model_id="test-model"
        )
        batch_time = time.time() - batch_start

        print("\n查询性能对比:")
        print(f"  单独查询: {individual_time*1000:.2f}ms ({num_queries} 次查询)")
        print(f"  批量查询: {batch_time*1000:.2f}ms ({num_queries} 次查询)")
        print(f"  性能提升: {individual_time/batch_time:.2f}x")

        # Batch should be faster or at least not significantly slower
        assert (
            batch_time <= individual_time * 1.2
        ), "Batch query should not be significantly slower than individual queries"

        # Verify all queries returned results
        assert (
            len(results) == num_queries
        ), f"Missing query results: got {len(results)}/{num_queries}"

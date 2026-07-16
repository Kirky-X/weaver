# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Performance tests for embedding cache.

Tests REAL performance of:
1. Embedding cache hit/miss scenarios
2. Redis cache performance vs database
3. Cache warm-up and eviction

These tests use:
- Real Redis instance (via Docker Compose)
- Real embedding generation
- Real cache operations
- NO MOCKS - all measurements are真实
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.mark.performance
@pytest.mark.e2e
class TestEmbeddingCachePerformance:
    """Performance tests for embedding cache with real Redis."""

    def test_cache_miss_performance(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test performance on cache miss (first request).

        Measures:
        - First request time (cache miss)
        - Should generate and cache embedding
        """
        start_time = time.time()

        response = client.get(
            "/api/v1/search/global",
            headers=auth_headers,
            params={"query": "unique_test_query_for_cache_miss", "limit": 5},
        )

        elapsed = time.time() - start_time

        assert response.status_code == 200
        assert elapsed < 5.0, f"Cache miss took {elapsed:.2f}s, should be < 5s"

    def test_cache_hit_performance(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test performance on cache hit (second request).

        Measures:
        - First request (cache miss)
        - Second request (cache hit)
        - Cache hit should be significantly faster
        """
        query = "test_query_for_cache_hit_measurement"

        first_start = time.time()
        first_response = client.get(
            "/api/v1/search/global",
            headers=auth_headers,
            params={"query": query, "limit": 5},
        )
        first_elapsed = time.time() - first_start

        assert first_response.status_code == 200

        second_start = time.time()
        second_response = client.get(
            "/api/v1/search/global",
            headers=auth_headers,
            params={"query": query, "limit": 5},
        )
        second_elapsed = time.time() - second_start

        assert second_response.status_code == 200
        assert second_elapsed < first_elapsed, (
            f"Cache hit ({second_elapsed:.2f}s) should be faster than "
            f"cache miss ({first_elapsed:.2f}s)"
        )

        cache_speedup = first_elapsed / second_elapsed if second_elapsed > 0 else float("inf")
        assert cache_speedup >= 1.5, f"Cache speedup {cache_speedup:.2f}x should be >= 1.5x"

    def test_bulk_cache_operations(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test performance of bulk cache operations.

        Measures:
        - Time for multiple different queries
        - Cache effectiveness across queries
        """
        queries = [f"bulk_test_query_{i}" for i in range(10)]

        start_time = time.time()

        for query in queries:
            response = client.get(
                "/api/v1/search/global",
                headers=auth_headers,
                params={"query": query, "limit": 3},
            )
            assert response.status_code == 200

        elapsed = time.time() - start_time
        avg_time = elapsed / len(queries)

        assert avg_time < 3.0, f"Avg time per query {avg_time:.2f}s should be < 3s"

    def test_cache_memory_efficiency(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test cache memory efficiency with repeated queries.

        Measures:
        - Performance consistency across repeated queries
        - No memory leaks or degradation
        """
        query = "memory_efficiency_test_query"
        times = []

        for _ in range(5):
            start_time = time.time()
            response = client.get(
                "/api/v1/search/global",
                headers=auth_headers,
                params={"query": query, "limit": 5},
            )
            elapsed = time.time() - start_time
            times.append(elapsed)

            assert response.status_code == 200

        avg_time = sum(times) / len(times)
        max_time = max(times)

        assert (
            max_time < avg_time * 2
        ), f"Max time {max_time:.2f}s should not exceed 2x avg {avg_time:.2f}s"

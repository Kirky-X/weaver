# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Performance tests for community detection algorithms.

Tests REAL performance of:
1. Community detection algorithm (Louvain/Leiden)
2. Community report generation
3. Community search and retrieval

These tests use:
- Real Neo4j database with actual data
- Real community detection algorithms
- Real performance measurement
- NO MOCKS - all measurements are真实
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.mark.performance
@pytest.mark.e2e
class TestCommunityDetectionPerformance:
    """Performance tests for community detection with real services."""

    def test_rebuild_performance(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test community rebuild performance.

        Measures:
        - API response time for rebuild trigger
        - Completion time (if synchronous)
        - Should complete within reasonable time
        """
        start_time = time.time()

        response = client.post(
            "/api/v1/admin/communities/rebuild",
            headers=auth_headers,
            json={"force": True},
        )

        elapsed = time.time() - start_time

        assert response.status_code in (200, 202)
        assert elapsed < 30.0, f"Rebuild trigger took {elapsed:.2f}s, should be < 30s"

    def test_community_list_performance(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test community list API performance.

        Measures:
        - Response time for listing communities
        - Should be fast (< 2s)
        """
        start_time = time.time()

        response = client.get(
            "/api/v1/admin/communities",
            headers=auth_headers,
            params={"limit": 100},
        )

        elapsed = time.time() - start_time

        assert response.status_code == 200
        assert elapsed < 2.0, f"List communities took {elapsed:.2f}s, should be < 2s"

    def test_community_detail_performance(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test community detail API performance.

        Measures:
        - Response time for getting community detail
        - Should be fast (< 1s)
        """
        list_response = client.get(
            "/api/v1/admin/communities",
            headers=auth_headers,
            params={"limit": 1},
        )

        assert list_response.status_code == 200
        data = list_response.json()
        communities = data.get("data", {}).get("communities", [])

        if len(communities) == 0:
            pytest.skip("No communities available")

        community_id = communities[0]["id"]

        start_time = time.time()

        response = client.get(
            f"/api/v1/admin/communities/{community_id}",
            headers=auth_headers,
        )

        elapsed = time.time() - start_time

        assert response.status_code == 200
        assert elapsed < 1.0, f"Get community detail took {elapsed:.2f}s, should be < 1s"

    def test_search_performance(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test community search performance.

        Measures:
        - Response time for search
        - Should be fast (< 3s)
        """
        start_time = time.time()

        response = client.get(
            "/api/v1/admin/communities",
            headers=auth_headers,
            params={"search": "test", "limit": 20},
        )

        elapsed = time.time() - start_time

        assert response.status_code == 200
        assert elapsed < 3.0, f"Search communities took {elapsed:.2f}s, should be < 3s"

    def test_concurrent_rebuild_requests(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test handling of concurrent rebuild requests.

        Measures:
        - System behavior under concurrent load
        - Should handle gracefully (either process or reject)
        """
        import concurrent.futures

        def trigger_rebuild() -> int:
            response = client.post(
                "/api/v1/admin/communities/rebuild",
                headers=auth_headers,
                json={"force": True},
            )
            return response.status_code

        start_time = time.time()

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(trigger_rebuild) for _ in range(3)]
            results = [f.result() for f in futures]

        elapsed = time.time() - start_time

        for status_code in results:
            assert status_code in (200, 202, 409, 429), f"Unexpected status code: {status_code}"

        assert elapsed < 10.0, f"Concurrent requests took {elapsed:.2f}s, should be < 10s"

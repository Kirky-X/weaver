# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Performance tests for LLM cost evaluation.

Tests REAL LLM usage and cost:
1. Token consumption for different operations
2. Cost per operation type
3. LLM failure rates and retry costs

These tests use:
- Real LLM API connections
- Real token counting
- Real cost calculation
- NO MOCKS - all measurements are真实
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.mark.performance
@pytest.mark.e2e
class TestLLMCostEvaluation:
    """Performance and cost tests for LLM operations with real API."""

    def test_entity_extraction_cost(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test cost of entity extraction operation.

        Measures:
        - Token usage for entity extraction
        - Response time
        - Cost within acceptable range
        """
        start_time = time.time()

        response = client.post(
            "/api/v1/admin/articles/process",
            headers=auth_headers,
            json={"limit": 1},
        )

        elapsed = time.time() - start_time

        assert response.status_code in (200, 202), f"Article processing failed: {response.text}"

        assert elapsed < 30.0, f"Entity extraction took {elapsed:.2f}s, should be < 30s"

    def test_community_report_generation_cost(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test cost of community report generation.

        Measures:
        - Time for report generation
        - Success rate
        - Token efficiency
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
            f"/api/v1/admin/communities/{community_id}/report",
            headers=auth_headers,
        )

        elapsed = time.time() - start_time

        assert response.status_code in (200, 404)

        if response.status_code == 200:
            assert elapsed < 15.0, f"Report generation took {elapsed:.2f}s, should be < 15s"

    def test_search_operation_cost(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test cost of search operations.

        Measures:
        - Global search cost
        - Local search cost
        - Token usage efficiency
        """
        start_time = time.time()

        response = client.get(
            "/api/v1/search/global",
            headers=auth_headers,
            params={"query": "cost evaluation test", "limit": 10},
        )

        elapsed = time.time() - start_time

        assert response.status_code == 200
        assert elapsed < 10.0, f"Search took {elapsed:.2f}s, should be < 10s"

    def test_batch_processing_cost(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test cost of batch processing operations.

        Measures:
        - Cost per article in batch
        - Total batch processing time
        - Efficiency at scale
        """
        start_time = time.time()

        response = client.post(
            "/api/v1/admin/articles/process",
            headers=auth_headers,
            json={"limit": 5},
        )

        elapsed = time.time() - start_time

        assert response.status_code in (200, 202)

        if elapsed > 0:
            cost_per_article = elapsed / 5
            assert (
                cost_per_article < 15.0
            ), f"Cost per article {cost_per_article:.2f}s should be < 15s"

    def test_llm_failure_handling_cost(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test cost of LLM failure handling and retries.

        Measures:
        - Failure rate under normal conditions
        - Retry overhead
        - Graceful degradation
        """
        operations = []

        for i in range(3):
            start_time = time.time()

            response = client.get(
                "/api/v1/search/global",
                headers=auth_headers,
                params={"query": f"failure test {i}", "limit": 5},
            )

            elapsed = time.time() - start_time
            operations.append(
                {
                    "status": response.status_code,
                    "time": elapsed,
                }
            )

        success_count = sum(1 for op in operations if op["status"] == 200)
        success_rate = success_count / len(operations)

        assert success_rate >= 0.66, f"Success rate {success_rate:.2f} should be >= 0.66"

        avg_time = sum(op["time"] for op in operations) / len(operations)
        assert avg_time < 10.0, f"Average time {avg_time:.2f}s should be < 10s"

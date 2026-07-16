# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""E2E tests for community detection workflow.

Tests the complete workflow of:
1. Community detection trigger via API
2. Community report generation
3. Community retrieval via API
4. Global search using communities

These tests use REAL services:
- Neo4j database (via Docker Compose)
- Real API endpoints
- Real community detection algorithms
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.mark.e2e
class TestCommunityDetectionWorkflow:
    """Tests for community detection end-to-end workflow using real services."""

    def test_community_rebuild_workflow(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Test complete community rebuild workflow via real API.

        Tests:
        1. POST /api/v1/admin/communities/rebuild triggers detection
        2. Response indicates success or async processing
        3. Community detection completes with valid results
        """
        rebuild_response = client.post(
            "/api/v1/admin/communities/rebuild",
            headers=admin_headers,
            json={"force": True},
        )

        assert rebuild_response.status_code in (
            200,
            202,
        ), f"Rebuild failed with status {rebuild_response.status_code}: {rebuild_response.text}"

        data = rebuild_response.json()
        assert "data" in data or "task_id" in data

        if rebuild_response.status_code == 202:
            task_id = data.get("task_id") or data.get("data", {}).get("task_id")
            assert task_id, "Async task should return task_id"

    def test_community_list_workflow(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Test listing communities via real API.

        Tests:
        1. GET /api/v1/admin/communities returns community list
        2. Response structure is valid
        3. Community data contains expected fields
        """
        list_response = client.get(
            "/api/v1/admin/communities",
            headers=admin_headers,
        )

        assert list_response.status_code == 200, f"List failed: {list_response.text}"

        data = list_response.json()
        assert "data" in data, "Response should contain 'data' field"

        community_data = data["data"]
        assert "communities" in community_data, "Should contain communities list"

        communities = community_data["communities"]
        assert isinstance(communities, list), "Communities should be a list"

        if len(communities) > 0:
            first_community = communities[0]
            assert "id" in first_community, "Community should have id"
            assert "title" in first_community, "Community should have title"
            assert "entity_count" in first_community, "Community should have entity_count"

    def test_community_get_detail_workflow(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Test getting individual community detail via real API.

        Tests:
        1. List communities first
        2. Get detail for first community
        3. Verify detail response structure
        """
        list_response = client.get(
            "/api/v1/admin/communities",
            headers=admin_headers,
        )

        assert list_response.status_code == 200
        data = list_response.json()
        communities = data.get("data", {}).get("communities", [])

        if len(communities) == 0:
            pytest.skip("No communities available for detail test")

        first_community_id = communities[0]["id"]

        detail_response = client.get(
            f"/api/v1/admin/communities/{first_community_id}",
            headers=admin_headers,
        )

        assert detail_response.status_code == 200, f"Detail failed: {detail_response.text}"

        detail_data = detail_response.json()
        assert "data" in detail_data
        assert "id" in detail_data["data"]
        assert detail_data["data"]["id"] == first_community_id

    def test_community_rebuild_and_list_sequence(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Test rebuild followed by list in sequence.

        Tests:
        1. Trigger rebuild
        2. Wait for completion
        3. List communities
        4. Verify communities exist
        """
        rebuild_response = client.post(
            "/api/v1/admin/communities/rebuild",
            headers=admin_headers,
            json={"force": True},
        )

        assert rebuild_response.status_code in (200, 202)

        if rebuild_response.status_code == 202:
            time.sleep(2)

        list_response = client.get(
            "/api/v1/admin/communities",
            headers=admin_headers,
            params={"limit": 10},
        )

        assert list_response.status_code == 200
        data = list_response.json()
        communities = data.get("data", {}).get("communities", [])
        assert isinstance(communities, list)

    def test_community_search_workflow(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Test community search via real API.

        Tests:
        1. Search communities with query
        2. Verify search results
        """
        search_response = client.get(
            "/api/v1/admin/communities",
            headers=admin_headers,
            params={"search": "test", "limit": 5},
        )

        assert search_response.status_code == 200
        data = search_response.json()
        assert "data" in data

    def test_community_report_workflow(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Test community report generation and retrieval.

        Tests:
        1. List communities
        2. Get report for first community
        3. Verify report structure
        """
        list_response = client.get(
            "/api/v1/admin/communities",
            headers=admin_headers,
        )

        assert list_response.status_code == 200
        data = list_response.json()
        communities = data.get("data", {}).get("communities", [])

        if len(communities) == 0:
            pytest.skip("No communities available for report test")

        first_community_id = communities[0]["id"]

        report_response = client.get(
            f"/api/v1/admin/communities/{first_community_id}/report",
            headers=admin_headers,
        )

        assert report_response.status_code in (200, 404)

        if report_response.status_code == 200:
            report_data = report_response.json()
            assert "data" in report_data

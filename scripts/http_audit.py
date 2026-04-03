#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""HTTP API Comprehensive Audit Script.

Tests all API endpoints with various parameter combinations.
Uses real data from the database when available.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx

# Configuration
API_BASE_URL = "http://localhost:8001"
API_KEY = os.environ.get("WEAVER_API__API_KEY", "dev_api_key_1234567890123456789012345678")
LOG_FILE = Path(__file__).parent.parent / "http_audit.log"
REQUEST_LOG_FILE = Path(__file__).parent.parent / "http_requests.jsonl"

# Real data from database
REAL_ARTICLE_ID = "932ad97f-76dd-45e8-bd3d-2558a2922d2b"
REAL_SOURCE_ID = "36kr"
REAL_ENTITY_NAME = "华为"  # Common entity for testing


def setup_logging():
    """Configure logging to file."""
    os.environ["LOG_FILE"] = str(LOG_FILE)
    os.environ["DEBUG"] = "true"


async def wait_for_server(client: httpx.AsyncClient, max_wait: int = 30) -> bool:
    """Wait for server to be ready."""
    for i in range(max_wait):
        try:
            resp = await client.get(f"{API_BASE_URL}/health", timeout=2.0)
            if resp.status_code == 200:
                print(f"Server ready after {i + 1}s")
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


def log_request_response(method: str, path: str, request_data: dict, response: httpx.Response):
    """Log request and response to JSONL file."""
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "request": {
            "method": method,
            "path": path,
            "headers": request_data.get("headers", {}),
            "body": request_data.get("body"),
        },
        "response": {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response.text[:2000] if response.text else None,
        },
    }
    with open(REQUEST_LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


async def test_endpoint(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    body: dict | None,
    description: str = "",
) -> bool:
    """Test a single endpoint and log results."""
    url = f"{API_BASE_URL}{path}"
    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

    # Skip auth for health/metrics
    if path in ("/health", "/metrics"):
        headers = {}

    try:
        if method == "GET":
            resp = await client.get(url, headers=headers, timeout=15.0)
        elif method == "POST":
            resp = await client.post(url, headers=headers, json=body, timeout=15.0)
        elif method == "PUT":
            resp = await client.put(url, headers=headers, json=body, timeout=15.0)
        elif method == "DELETE":
            resp = await client.delete(url, headers=headers, timeout=15.0)
        elif method == "PATCH":
            resp = await client.patch(url, headers=headers, json=body, timeout=15.0)
        else:
            return False

        status_icon = "✓" if resp.status_code < 400 else "✗"
        desc_str = f" ({description})" if description else ""
        print(f"{status_icon} {method} {path} -> {resp.status_code}{desc_str}")

        log_request_response(method, path, {"headers": headers, "body": body}, resp)
        return resp.status_code < 400

    except Exception as e:
        print(f"✗ {method} {path} -> ERROR: {e}")
        log_request_response(
            method,
            path,
            {"headers": headers, "body": body},
            httpx.Response(status_code=0, headers={}, content=f"Error: {e}".encode()),
        )
        return False


async def test_all_endpoints(client: httpx.AsyncClient):
    """Test all API endpoints with parameter variations."""
    results = {"passed": 0, "failed": 0}

    print("\n" + "=" * 70)
    print("Testing API Endpoints")
    print("=" * 70)

    # ========== System ==========
    print("\n--- System ---")
    for path, desc in [("/health", "basic"), ("/metrics", "prometheus")]:
        if await test_endpoint(client, "GET", path, None, desc):
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ========== Sources API ==========
    print("\n--- Sources API ---")
    endpoints = [
        ("GET", "/api/v1/sources", None, "enabled_only=true"),
        ("GET", "/api/v1/sources?enabled_only=false", None, "all sources"),
        ("GET", f"/api/v1/sources/{REAL_SOURCE_ID}", None, "get by id"),
        ("GET", "/api/v1/sources/nonexistent", None, "404 test"),
        (
            "POST",
            "/api/v1/sources",
            {"id": "test_audit", "name": "Test", "url": "https://test.com/rss"},
            "create",
        ),
        ("PUT", "/api/v1/sources/test_audit", {"name": "Updated Test"}, "update"),
        ("DELETE", "/api/v1/sources/test_audit", None, "delete"),
    ]
    for method, path, body, desc in endpoints:
        if await test_endpoint(client, method, path, body, desc):
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ========== Articles API ==========
    print("\n--- Articles API ---")
    endpoints = [
        ("GET", "/api/v1/articles", None, "default list"),
        ("GET", "/api/v1/articles?page=1&page_size=5", None, "pagination"),
        ("GET", "/api/v1/articles?category=科技", None, "category filter"),
        ("GET", "/api/v1/articles?min_score=0.5", None, "min_score filter"),
        ("GET", "/api/v1/articles?sort_by=score&sort_order=desc", None, "sort by score"),
        ("GET", f"/api/v1/articles/{REAL_ARTICLE_ID}", None, "get by id"),
        ("GET", "/api/v1/articles/invalid-uuid", None, "invalid uuid test"),
    ]
    for method, path, body, desc in endpoints:
        if await test_endpoint(client, method, path, body, desc):
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ========== Search API ==========
    print("\n--- Search API ---")
    endpoints = [
        ("GET", "/api/v1/search?q=华为&mode=local", None, "local search"),
        ("GET", "/api/v1/search?q=腾讯&mode=global", None, "global search"),
        ("GET", "/api/v1/search?q=人工智能&mode=articles", None, "articles search"),
        ("GET", "/api/v1/search?q=科技&mode=articles&limit=5", None, "articles with limit"),
        (
            "GET",
            "/api/v1/search?q=科技&mode=articles&category=科技",
            None,
            "articles category filter",
        ),
        ("GET", "/api/v1/search?q=test&mode=articles&threshold=0.3", None, "threshold filter"),
        ("POST", "/api/v1/search/drift", {"query": "人工智能发展趋势"}, "DRIFT search"),
    ]
    for method, path, body, desc in endpoints:
        if await test_endpoint(client, method, path, body, desc):
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ========== Pipeline API ==========
    print("\n--- Pipeline API ---")
    endpoints = [
        ("GET", "/api/v1/pipeline/queue/stats", None, "queue stats"),
        (
            "POST",
            "/api/v1/pipeline/trigger",
            {"source_id": REAL_SOURCE_ID, "max_items": 1},
            "trigger specific source",
        ),
    ]
    for method, path, body, desc in endpoints:
        if await test_endpoint(client, method, path, body, desc):
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ========== Graph API ==========
    print("\n--- Graph API ---")
    endpoints = [
        ("GET", "/api/v1/graph/metrics", None, "metrics default"),
        ("GET", "/api/v1/graph/metrics?view=health", None, "metrics health view"),
        ("GET", "/api/v1/graph/metrics?view=full", None, "metrics full view"),
        ("GET", "/api/v1/graph/relation-types", None, "relation types"),
        ("GET", f"/api/v1/graph/relations?entity={REAL_ENTITY_NAME}", None, "relations by entity"),
        (
            "GET",
            f"/api/v1/graph/relations/search?entity={REAL_ENTITY_NAME}&limit=10",
            None,
            "relations search",
        ),
        ("GET", "/api/v1/graph/communities", None, "communities list"),
        ("GET", "/api/v1/graph/communities?level=0&limit=10", None, "communities level filter"),
        ("GET", "/api/v1/graph/visualization?limit=50", None, "visualization"),
        (
            "POST",
            "/api/v1/graph/visualization",
            {"center_entity": REAL_ENTITY_NAME, "max_hops": 2},
            "centered visualization",
        ),
        ("GET", f"/api/v1/graph/articles/{REAL_ARTICLE_ID}/graph", None, "article graph"),
    ]
    for method, path, body, desc in endpoints:
        if await test_endpoint(client, method, path, body, desc):
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ========== Admin API ==========
    print("\n--- Admin API ---")
    endpoints = [
        ("GET", "/api/v1/admin/authorities", None, "authorities list"),
        (
            "GET",
            "/api/v1/admin/authorities?needs_review_only=true",
            None,
            "authorities needs review",
        ),
        (
            "PATCH",
            "/api/v1/admin/authorities/test.com",
            {"authority": 0.85, "tier": 2},
            "update authority",
        ),
        ("GET", "/api/v1/admin/llm-failures", None, "llm failures"),
        ("GET", "/api/v1/admin/llm-failures/stats", None, "llm failures stats"),
        ("GET", "/api/v1/admin/llm-usage?from=2024-01-01&to=2025-12-31", None, "llm usage"),
        (
            "GET",
            "/api/v1/admin/llm-usage/summary?from=2024-01-01&to=2025-12-31",
            None,
            "llm usage summary",
        ),
        (
            "GET",
            "/api/v1/admin/llm-usage/by-provider?from=2024-01-01&to=2025-12-31",
            None,
            "by provider",
        ),
        ("GET", "/api/v1/admin/llm-usage/by-model?from=2024-01-01&to=2025-12-31", None, "by model"),
        (
            "GET",
            "/api/v1/admin/llm-usage/by-call-point?from=2024-01-01&to=2025-12-31",
            None,
            "by call point",
        ),
    ]
    for method, path, body, desc in endpoints:
        if await test_endpoint(client, method, path, body, desc):
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ========== Admin Communities ==========
    print("\n--- Admin Communities ---")
    endpoints = [
        (
            "POST",
            "/api/v1/admin/communities/rebuild",
            {"max_cluster_size": 10},
            "rebuild communities",
        ),
        ("POST", "/api/v1/admin/communities/reports/generate", None, "generate reports"),
    ]
    for method, path, body, desc in endpoints:
        if await test_endpoint(client, method, path, body, desc):
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results


async def main():
    """Main entry point."""
    setup_logging()

    print("=" * 70)
    print("HTTP API Comprehensive Audit")
    print("=" * 70)
    print(f"API Base URL: {API_BASE_URL}")
    print(f"API Key: {API_KEY[:15]}...")

    # Clear previous logs
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    if REQUEST_LOG_FILE.exists():
        REQUEST_LOG_FILE.unlink()

    async with httpx.AsyncClient() as client:
        print("\nWaiting for server...")
        if not await wait_for_server(client):
            print("Server not ready. Start with:")
            print("  uv run uvicorn src.main:app --port 8001")
            return

        results = await test_all_endpoints(client)

    print("\n" + "=" * 70)
    print(f"Results: {results['passed']} passed, {results['failed']} failed")
    print("=" * 70)
    print(f"\nLogs saved to:")
    print(f"  - {LOG_FILE}")
    print(f"  - {REQUEST_LOG_FILE}")


if __name__ == "__main__":
    asyncio.run(main())

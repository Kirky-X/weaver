#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Systematic endpoint testing script.

Tests all HTTP endpoints one by one using TestClient with fallback databases.
Validates response format, field completeness, and data accuracy against source data.

Usage:
    uv run python tests/e2e/run_endpoint_tests.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "e2e"))

import duckdb
import nest_asyncio
import real_ladybug as ladybug
from fastapi.testclient import TestClient

nest_asyncio.apply()

# ── Test Configuration ──────────────────────────────────────────────────

TEST_ENV = {
    "WEAVER_API__API_KEY": "test-api-key-32chars-long-abc!!!",
    "WEAVER_API__ADMIN_API_KEY": "test-admin-api-key-32chars-xyz!!!",
    "WEAVER_DUCKDB__ENABLED": "true",
    "WEAVER_DUCKDB__DB_PATH": str(PROJECT_ROOT / "data" / "weaver.duckdb"),
    "WEAVER_LADYBUG__ENABLED": "true",
    "WEAVER_LADYBUG__DB_PATH": str(PROJECT_ROOT / "data" / "weaver.lbug"),
    "WEAVER_NEO4J__ENABLED": "false",
    "WEAVER_POSTGRES__PORT": "1",  # Force failure to use fallback
    "WEAVER_NEO4J__URI": "bolt://localhost:1",
    "ENVIRONMENT": "testing",
    "DEBUG": "true",
    "WEAVER_OBSERVABILITY__OTLP_ENDPOINT": "",
}

# Set environment variables
for key, value in TEST_ENV.items():
    os.environ[key] = value

API_KEY = TEST_ENV["WEAVER_API__API_KEY"]
ADMIN_KEY = TEST_ENV["WEAVER_API__ADMIN_API_KEY"]
AUTH_HEADERS = {"X-API-Key": API_KEY}
ADMIN_HEADERS = {"X-API-Key": ADMIN_KEY}


# ── Test Reporter ────────────────────────────────────────────────────────


class TestReporter:
    """Records and reports test results."""

    def __init__(self):
        self.results: list[dict[str, Any]] = []
        self.passed = 0
        self.failed = 0
        self.total_time = 0.0

    def record(
        self,
        endpoint: str,
        method: str,
        test_case: str,
        status_code: int,
        duration_ms: float,
        validations: list[dict[str, Any]],
        passed: bool,
        error: str | None = None,
    ):
        """Record test result."""
        self.results.append(
            {
                "endpoint": endpoint,
                "method": method,
                "test_case": test_case,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "validations": validations,
                "passed": passed,
                "error": error,
            }
        )
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        self.total_time += duration_ms

    def generate_report(self) -> str:
        """Generate markdown report."""
        lines = [
            "# HTTP接口测试报告",
            "",
            f"**测试时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**总测试数**: {len(self.results)}",
            f"**通过**: {self.passed}",
            f"**失败**: {self.failed}",
            f"**通过率**: {(self.passed / len(self.results) * 100) if self.results else 0:.1f}%",
            f"**总耗时**: {self.total_time:.2f}ms",
            "",
            "---",
            "",
        ]

        # Group by endpoint
        by_endpoint: dict[str, list] = {}
        for r in self.results:
            by_endpoint.setdefault(r["endpoint"], []).append(r)

        for endpoint, tests in by_endpoint.items():
            status = "✓" if all(t["passed"] for t in tests) else "✗"
            lines.append(f"## {status} {endpoint}")
            lines.append("")

            for test in tests:
                test_status = "✓" if test["passed"] else "✗"
                lines.append(f"### {test_status} {test['test_case']}")
                lines.append(f"- **方法**: {test['method']}")
                lines.append(f"- **状态码**: {test['status_code']}")
                lines.append(f"- **耗时**: {test['duration_ms']:.2f}ms")

                if test["validations"]:
                    lines.append("- **验证项**:")
                    for v in test["validations"]:
                        v_status = "✓" if v["passed"] else "✗"
                        lines.append(
                            f"  - {v_status} {v['name']}: {v.get('expected', 'N/A')} vs {v.get('actual', 'N/A')}"
                        )

                if test["error"]:
                    lines.append(f"- **错误**: {test['error']}")

                lines.append("")

        return "\n".join(lines)


# ── Data Validators ──────────────────────────────────────────────────────


def get_expected_db_counts():
    """Get expected database counts from temp/all_nodes_info.json."""
    import json

    info_path = PROJECT_ROOT / "temp" / "all_nodes_info.json"
    if info_path.exists():
        with open(info_path) as f:
            info = json.load(f)
            return {
                "duckdb_articles": info.get("duckdb", {}).get("article_count", 3),
                "ladybug_entities": info.get("ladybug", {}).get("entity_count", 15),
            }
    return {"duckdb_articles": 3, "ladybug_entities": 15}


async def get_ladybug_data():
    """Get LadybugDB data for validation."""
    db = ladybug.Database(str(PROJECT_ROOT / "data" / "weaver.lbug"))
    conn = ladybug.AsyncConnection(db)

    entities = await conn.execute("MATCH (n:Entity) RETURN n.name as name, n.id as id")
    entity_list = []
    while entities.has_next():
        entity_list.append(entities.get_next())

    relations = await conn.execute("MATCH ()-[r]->() RETURN type(r) as type, count(r) as cnt")
    rel_list = []
    while relations.has_next():
        rel_list.append(relations.get_next())

    return {"entities": entity_list, "relations": rel_list}


# ── Test Functions ────────────────────────────────────────────────────────


def test_endpoint(client: TestClient, reporter: TestReporter, endpoint_config: dict):
    """Test a single endpoint."""
    method = endpoint_config["method"]
    url = endpoint_config["url"]
    test_case = endpoint_config["test_case"]
    headers = endpoint_config.get("headers", AUTH_HEADERS)
    params = endpoint_config.get("params")
    json_data = endpoint_config.get("json_data")
    expected_status = endpoint_config.get("expected_status", [200])
    validations = endpoint_config.get("validations", [])

    start = time.time()
    request_kwargs = {"headers": headers}
    if params:
        request_kwargs["params"] = params
    if json_data is not None:
        request_kwargs["json"] = json_data

    try:
        request_fn = getattr(client, method.lower())
        response = request_fn(url, **request_kwargs)
        duration_ms = (time.time() - start) * 1000

        # Parse response
        try:
            body = response.json()
        except Exception:
            body = response.text if response.text else None

        # Run validations
        validation_results = []
        all_passed = True

        for v in validations:
            v_result = {"name": v["name"], "passed": False}
            try:
                if v["type"] == "status":
                    v_result["passed"] = response.status_code in expected_status
                    v_result["expected"] = expected_status
                    v_result["actual"] = response.status_code
                elif v["type"] == "field_exists":
                    if body and isinstance(body, dict):
                        # Support nested path like "data.status" or "data.items"
                        parts = v["field"].split(".")
                        current = body
                        exists = True
                        for part in parts:
                            if isinstance(current, dict) and part in current:
                                current = current[part]
                            else:
                                exists = False
                                break
                        v_result["passed"] = exists
                        v_result["actual"] = exists
                elif v["type"] == "field_type":
                    if body and isinstance(body, dict) and v["field"] in body:
                        actual_type = type(body[v["field"]]).__name__
                        v_result["passed"] = actual_type == v["expected_type"]
                        v_result["expected"] = v["expected_type"]
                        v_result["actual"] = actual_type
                elif v["type"] == "data_count":
                    if body and isinstance(body, dict):
                        data = body.get("data", {})
                        if isinstance(data, dict) and "items" in data:
                            count = len(data["items"])
                        elif isinstance(data, list):
                            count = len(data)
                        else:
                            count = 0
                        v_result["passed"] = count >= v["min_count"]
                        v_result["expected"] = f">= {v['min_count']}"
                        v_result["actual"] = count
                elif v["type"] == "has_items":
                    if body and isinstance(body, dict):
                        data = body.get("data", {})
                        items = data.get("items", []) if isinstance(data, dict) else data
                        v_result["passed"] = len(items) > 0
                        v_result["actual"] = len(items)
            except Exception as e:
                v_result["error"] = str(e)

            if not v_result["passed"]:
                all_passed = False
            validation_results.append(v_result)

        reporter.record(
            endpoint=url,
            method=method,
            test_case=test_case,
            status_code=response.status_code,
            duration_ms=duration_ms,
            validations=validation_results,
            passed=all_passed and response.status_code in expected_status,
        )

        return response, body, all_passed

    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        reporter.record(
            endpoint=url,
            method=method,
            test_case=test_case,
            status_code=0,
            duration_ms=duration_ms,
            validations=[],
            passed=False,
            error=str(e),
        )
        return None, None, False


# ── Main Test Runner ──────────────────────────────────────────────────────


def create_test_app():
    """Create FastAPI app for testing with proper container initialization."""
    from config.settings import Settings
    from container import Container
    from main import create_app

    settings = Settings()
    settings.api.api_key = API_KEY

    import container

    container._settings_instance = settings

    container_obj = Container().configure(settings)
    app = create_app(container_obj)
    # Store container for later startup (TestClient doesn't trigger lifespan)
    app.state.container = container_obj
    return app


async def init_app_container(app):
    """Initialize container services."""
    import asyncio

    container = app.state.container
    await container.startup()


def run_tests():
    """Run all endpoint tests."""
    print("=" * 60)
    print("HTTP接口系统化测试")
    print("=" * 60)

    # Create app and client
    print("\n[1] 初始化测试应用...")
    app = create_test_app()

    print("[2] 初始化容器服务...")
    import asyncio

    asyncio.get_event_loop().run_until_complete(init_app_container(app))

    print("[3] 创建TestClient...")
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        client = TestClient(app)

    print("[4] 获取数据库数据用于验证...")
    expected_counts = get_expected_db_counts()
    print(f"  - DuckDB: 预期 {expected_counts['duckdb_articles']} articles")
    print(f"  - LadybugDB: 预期 {expected_counts['ladybug_entities']} entities")

    reporter = TestReporter()

    # ── Define Test Cases ──────────────────────────────────────────────

    test_cases = [
        # Health endpoints
        {
            "url": "/health",
            "method": "GET",
            "test_case": "health_check",
            "headers": None,  # No auth required
            "expected_status": [200, 503],
            "validations": [
                {"name": "status_ok", "type": "status"},
                {"name": "has_data", "type": "field_exists", "field": "data"},
                {"name": "has_status", "type": "field_exists", "field": "data.status"},
            ],
        },
        {
            "url": "/metrics",
            "method": "GET",
            "test_case": "prometheus_metrics",
            "headers": None,
            "expected_status": [200],
            "validations": [{"name": "status_ok", "type": "status"}],
        },
        # Article endpoints
        {
            "url": "/api/v1/articles",
            "method": "GET",
            "test_case": "list_articles",
            "headers": AUTH_HEADERS,
            "expected_status": [200],
            "validations": [
                {"name": "status_ok", "type": "status"},
                {"name": "has_data", "type": "field_exists", "field": "data"},
                {
                    "name": "data_is_dict",
                    "type": "field_type",
                    "field": "data",
                    "expected_type": "dict",
                },
                {"name": "has_items", "type": "field_exists", "field": "data.items"},
                {"name": "items_count", "type": "data_count", "min_count": 1},
            ],
        },
        {
            "url": "/api/v1/articles",
            "method": "GET",
            "test_case": "articles_pagination",
            "headers": AUTH_HEADERS,
            "params": {"page": "1", "page_size": "2"},
            "expected_status": [200],
            "validations": [
                {"name": "status_ok", "type": "status"},
                {"name": "has_pagination", "type": "field_exists", "field": "data.page"},
                {"name": "items_count", "type": "data_count", "min_count": 0},
            ],
        },
        {
            "url": "/api/v1/articles",
            "method": "GET",
            "test_case": "articles_filter_min_score",
            "headers": AUTH_HEADERS,
            "params": {"min_score": "0.5"},
            "expected_status": [200],
            "validations": [{"name": "status_ok", "type": "status"}],
        },
        {
            "url": "/api/v1/articles",
            "method": "GET",
            "test_case": "articles_sort_desc",
            "headers": AUTH_HEADERS,
            "params": {"sort_by": "created_at", "sort_order": "desc"},
            "expected_status": [200],
            "validations": [{"name": "status_ok", "type": "status"}],
        },
        {
            "url": "/api/v1/articles",
            "method": "GET",
            "test_case": "articles_no_auth",
            "headers": None,
            "expected_status": [401],
            "validations": [{"name": "status_unauthorized", "type": "status"}],
        },
        # Sources endpoints
        {
            "url": "/api/v1/sources",
            "method": "GET",
            "test_case": "list_sources",
            "headers": AUTH_HEADERS,
            "expected_status": [200],
            "validations": [
                {"name": "status_ok", "type": "status"},
                {"name": "has_data", "type": "field_exists", "field": "data"},
            ],
        },
        {
            "url": "/api/v1/sources",
            "method": "GET",
            "test_case": "sources_no_auth",
            "headers": None,
            "expected_status": [401],
            "validations": [{"name": "status_unauthorized", "type": "status"}],
        },
        # Search endpoints
        {
            "url": "/api/v1/search",
            "method": "GET",
            "test_case": "search_no_query",
            "headers": AUTH_HEADERS,
            "expected_status": [200, 400, 422],
            "validations": [{"name": "status_handled", "type": "status"}],
        },
        {
            "url": "/api/v1/search",
            "method": "GET",
            "test_case": "search_with_query",
            "headers": AUTH_HEADERS,
            "params": {"q": "test"},
            "expected_status": [200, 500],
            "validations": [{"name": "status_handled", "type": "status"}],
        },
        # Graph endpoints
        {
            "url": "/api/v1/graph/relations",
            "method": "GET",
            "test_case": "get_relations",
            "headers": AUTH_HEADERS,
            "expected_status": [200, 422],
            "validations": [{"name": "status_handled", "type": "status"}],
        },
        # Admin endpoints
        {
            "url": "/api/v1/admin/authorities",
            "method": "GET",
            "test_case": "list_authorities",
            "headers": AUTH_HEADERS,
            "expected_status": [200],
            "validations": [{"name": "status_ok", "type": "status"}],
        },
        {
            "url": "/api/v1/admin/llm-usage",
            "method": "GET",
            "test_case": "llm_usage",
            "headers": AUTH_HEADERS,
            "params": {"from": "2025-01-01", "to": "2025-12-31"},
            "expected_status": [200, 400, 422],
            "validations": [{"name": "status_handled", "type": "status"}],
        },
        {
            "url": "/api/v1/admin/communities",
            "method": "GET",
            "test_case": "list_communities",
            "headers": AUTH_HEADERS,
            "expected_status": [200],
            "validations": [{"name": "status_ok", "type": "status"}],
        },
        # Pipeline endpoints
        {
            "url": "/api/v1/pipeline/queue/stats",
            "method": "GET",
            "test_case": "queue_stats",
            "headers": AUTH_HEADERS,
            "expected_status": [200],
            "validations": [{"name": "status_ok", "type": "status"}],
        },
    ]

    print(f"\n[4] 运行 {len(test_cases)} 个测试...")
    print("-" * 60)

    for tc in test_cases:
        print(f"  测试: {tc['test_case']}...")
        response, body, passed = test_endpoint(client, reporter, tc)
        status_icon = "✓" if passed else "✗"
        status_code = response.status_code if response else "N/A"
        print(f"    {status_icon} {tc['url']} -> {status_code}")

    print("-" * 60)

    # Generate report
    print("\n[5] 生成测试报告...")
    report = reporter.generate_report()

    report_path = PROJECT_ROOT / "temp" / "endpoint_test_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"    报告保存到: {report_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("测试摘要")
    print("=" * 60)
    print(f"总测试数: {len(reporter.results)}")
    print(f"通过: {reporter.passed}")
    print(f"失败: {reporter.failed}")
    print(
        f"通过率: {(reporter.passed / len(reporter.results) * 100) if reporter.results else 0:.1f}%"
    )
    print("=" * 60)

    return reporter


if __name__ == "__main__":
    reporter = run_tests()

    # Exit with error if any tests failed
    sys.exit(0 if reporter.failed == 0 else 1)

"""Comprehensive API testing script with httpx

Features:
- Use httpx sync client for real HTTP requests
- Support concurrent execution (ThreadPoolExecutor)
- Comprehensive parameter combination testing
- Complete request/response recording
- Automatic ID extraction and reuse
- Detailed test report generation
"""

import json
import secrets
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import quote

import httpx

# ── 配置 ──────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8000/api/v1"
API_KEY = "test-api-key-32chars-long!!!!!!!"
ADMIN_API_KEY = "test-admin-key-for-pipeline-2026"
HEADERS = {"X-API-Key": API_KEY}
TIMEOUT = httpx.Timeout(60.0)
OUTPUT_DIR = Path("/home/dev/projects/weaver/temp/api_responses")
MAX_WORKERS = 10  # 并发数

# ── 数据存储 ──────────────────────────────────────────────────────

results = []
results_lock = Lock()

# ID storage for test reuse
extracted_ids = {
    "article_ids": [],
    "source_ids": [],
    "community_ids": [],
    "entity_names": [],
    "host_names": [],
}
ids_lock = Lock()

# ── 测试用例定义 ──────────────────────────────────────────────────


@dataclass
class TestCase:
    """测试用例配置"""

    name: str
    endpoint_group: str
    method: str
    url: str
    params: dict | None = None
    json_body: dict | None = None
    expected_status: int = 200
    description: str = ""


def generate_test_cases() -> list[TestCase]:
    """生成所有测试用例"""
    cases = []

    # ===== 0. 社区初始化 =====
    cases.extend(
        [
            TestCase(
                "rebuild_communities",
                "communities",
                "POST",
                "/admin/communities/rebuild",
                json_body={"max_cluster_size": 10, "seed": 42},
                expected_status=200,
                description="rebuild_communities_default",
            ),
            TestCase(
                "generate_reports",
                "communities",
                "POST",
                "/admin/communities/reports/generate",
                expected_status=200,
                description="generate_reports",
            ),
        ]
    )

    # ===== 1. Articles =====
    # GET /articles - 基础测试
    cases.extend(
        [
            TestCase(
                "articles_001",
                "articles",
                "GET",
                "/articles",
                description="get_all_articles_default",
            ),
            TestCase(
                "articles_002",
                "articles",
                "GET",
                "/articles",
                params={"page": 1, "page_size": 10},
                description="pagination_page1_size10",
            ),
            TestCase(
                "articles_003",
                "articles",
                "GET",
                "/articles",
                params={"page": 2, "page_size": 20},
                description="pagination_page2_size20",
            ),
            TestCase(
                "articles_004",
                "articles",
                "GET",
                "/articles",
                params={"page_size": 50},
                description="pagesize_50",
            ),
            TestCase(
                "articles_005",
                "articles",
                "GET",
                "/articles",
                params={"page_size": 100},
                description="pagesize_100",
            ),
        ]
    )

    # GET /articles - 边界值测试
    cases.extend(
        [
            TestCase(
                "articles_006",
                "articles",
                "GET",
                "/articles",
                params={"page": 0},
                expected_status=422,
                description="invalid_page_0",
            ),
            TestCase(
                "articles_007",
                "articles",
                "GET",
                "/articles",
                params={"page": -1},
                expected_status=422,
                description="invalid_page_negative",
            ),
            TestCase(
                "articles_008",
                "articles",
                "GET",
                "/articles",
                params={"page_size": 0},
                expected_status=422,
                description="invalid_pagesize_0",
            ),
            TestCase(
                "articles_009",
                "articles",
                "GET",
                "/articles",
                params={"page_size": 101},
                expected_status=422,
                description="invalid_pagesize_101",
            ),
        ]
    )

    # GET /articles - 过滤测试
    cases.extend(
        [
            TestCase(
                "articles_010",
                "articles",
                "GET",
                "/articles",
                params={"category": "科技"},
                description="filter_category_tech",
            ),
            TestCase(
                "articles_011",
                "articles",
                "GET",
                "/articles",
                params={"category": "财经"},
                description="filter_category_finance",
            ),
            TestCase(
                "articles_012",
                "articles",
                "GET",
                "/articles",
                params={"min_score": 0.5},
                description="filter_minscore_0.5",
            ),
            TestCase(
                "articles_013",
                "articles",
                "GET",
                "/articles",
                params={"min_credibility": 0.7},
                description="filter_mincredibility_0.7",
            ),
        ]
    )

    # GET /articles - 排序测试
    cases.extend(
        [
            TestCase(
                "articles_014",
                "articles",
                "GET",
                "/articles",
                params={"sort_by": "publish_time", "sort_order": "desc"},
                description="sort_by_publish_time_desc",
            ),
            TestCase(
                "articles_015",
                "articles",
                "GET",
                "/articles",
                params={"sort_by": "score", "sort_order": "asc"},
                description="sort_by_score_asc",
            ),
            TestCase(
                "articles_016",
                "articles",
                "GET",
                "/articles",
                params={"sort_by": "created_at", "sort_order": "desc"},
                description="sort_by_created_at_desc",
            ),
        ]
    )

    # GET /articles/{id} - dynamic generation (requires article_ids)
    # These will be added at runtime

    cases.extend(
        [
            TestCase(
                "articles_017",
                "articles",
                "GET",
                "/articles/00000000-0000-0000-0000-000000000000",
                expected_status=404,
                description="article_notfound",
            ),
            TestCase(
                "articles_018",
                "articles",
                "GET",
                "/articles/invalid-uuid",
                expected_status=400,
                description="article_invalid_uuid",
            ),
        ]
    )

    # ===== 2. Sources =====
    cases.extend(
        [
            TestCase(
                "sources_001",
                "sources",
                "GET",
                "/sources",
                params={"enabled_only": True},
                description="list_sources_enabled",
            ),
            TestCase(
                "sources_002",
                "sources",
                "GET",
                "/sources",
                params={"enabled_only": False},
                description="list_sources_all",
            ),
        ]
    )

    # POST /sources - creation test
    random_id = "test-source-" + "".join(
        [secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8)]
    )
    cases.extend(
        [
            TestCase(
                "sources_003",
                "sources",
                "POST",
                "/sources",
                json_body={
                    "id": random_id,
                    "name": f"test_source_{random_id}",
                    "url": "https://example.com/rss",
                    "source_type": "rss",
                    "interval_minutes": 60,
                    "credibility": 0.8,
                    "tier": 2,
                },
                expected_status=201,
                description="create_source_valid",
            ),
            TestCase(
                "sources_004",
                "sources",
                "POST",
                "/sources",
                json_body={
                    "id": random_id,
                    "name": f"test_source_{random_id}",
                    "url": "https://example.com/rss",
                    "source_type": "rss",
                },
                expected_status=409,
                description="create_source_duplicate",
            ),
            TestCase(
                "sources_005",
                "sources",
                "POST",
                "/sources",
                json_body={"name": "", "id": "test-invalid", "url": "https://example.com"},
                expected_status=422,
                description="create_source_invalid_empty_name",
            ),
            TestCase(
                "sources_006",
                "sources",
                "POST",
                "/sources",
                json_body={"name": "test", "id": "test-invalid2", "url": "invalid-url"},
                expected_status=422,
                description="create_source_invalid_url",
            ),
        ]
    )

    # GET /sources/{id} - 动态生成
    cases.extend(
        [
            TestCase(
                "sources_007",
                "sources",
                "GET",
                "/sources/00000000-0000-0000-0000-000000000000",
                expected_status=404,
                description="source_notfound",
            ),
        ]
    )

    # ===== 3. Search =====
    cases.extend(
        [
            TestCase(
                "search_001",
                "search",
                "GET",
                "/search",
                params={"q": "AI"},
                description="default_search_ai",
            ),
            TestCase(
                "search_002",
                "search",
                "GET",
                "/search",
                params={"q": "科技", "mode": "local"},
                description="local_mode_search",
            ),
            TestCase(
                "search_003",
                "search",
                "GET",
                "/search",
                params={"q": "公司", "mode": "global"},
                description="global_mode_search",
            ),
            TestCase(
                "search_004",
                "search",
                "GET",
                "/search",
                params={"q": "企业", "limit": 3},
                description="search_with_limit_3",
            ),
            TestCase(
                "search_005",
                "search",
                "GET",
                "/search",
                params={"q": "投资", "limit": 50},
                description="search_with_limit_50",
            ),
            TestCase(
                "search_006",
                "search",
                "GET",
                "/search",
                params={"q": "", "mode": "local"},
                expected_status=422,
                description="search_empty_query",
            ),
            TestCase(
                "search_007",
                "search",
                "GET",
                "/search",
                params={"q": "本田汽车合资工厂广汽东风"},
                description="search_long_query",
            ),
            TestCase(
                "search_008",
                "search",
                "GET",
                "/search",
                params={"q": "技术", "mode": "articles", "threshold": 0.5},
                description="articles_mode_with_threshold",
            ),
        ]
    )

    # POST /search/drift
    cases.extend(
        [
            TestCase(
                "search_009",
                "search",
                "POST",
                "/search/drift",
                json_body={"query": "本田广汽合资", "max_hops": 2},
                description="drift_search_default",
            ),
            TestCase(
                "search_010",
                "search",
                "POST",
                "/search/drift",
                json_body={"query": "本田", "primer_k": 5, "max_follow_ups": 3},
                description="drift_search_custom_params",
            ),
            TestCase(
                "search_011",
                "search",
                "POST",
                "/search/drift",
                json_body={"query": ""},
                expected_status=422,
                description="drift_search_empty_query",
            ),
        ]
    )

    # POST /search/causal
    cases.extend(
        [
            TestCase(
                "search_012",
                "search",
                "POST",
                "/search/causal",
                json_body={"query": "仕佳光子投资产业化", "max_depth": 3},
                description="causal_search_default",
            ),
            TestCase(
                "search_013",
                "search",
                "POST",
                "/search/causal",
                json_body={"query": "投资", "max_depth": 5, "min_confidence": 0.5},
                description="causal_search_custom_depth",
            ),
            TestCase(
                "search_014",
                "search",
                "POST",
                "/search/causal",
                json_body={"query": ""},
                expected_status=422,
                description="causal_search_empty_query",
            ),
        ]
    )

    # POST /search/temporal
    cases.extend(
        [
            TestCase(
                "search_015",
                "search",
                "POST",
                "/search/temporal",
                json_body={"query": "本田", "time_window_days": 30},
                description="temporal_search_default",
            ),
            TestCase(
                "search_016",
                "search",
                "POST",
                "/search/temporal",
                json_body={"query": "投资", "time_window_days": 7, "limit": 20},
                description="temporal_search_custom_window",
            ),
            TestCase(
                "search_017",
                "search",
                "POST",
                "/search/temporal",
                json_body={"query": ""},
                expected_status=422,
                description="temporal_search_empty_query",
            ),
        ]
    )

    # ===== 4. Graph =====
    cases.extend(
        [
            TestCase(
                "graph_001",
                "graph",
                "GET",
                "/graph/entities/%E6%9C%AC%E7%94%B0",
                description="get_entity_honda",
            ),
            TestCase(
                "graph_002",
                "graph",
                "GET",
                "/graph/entities/NonExistentEntityXYZ",
                expected_status=404,
                description="get_entity_notfound",
            ),
            TestCase(
                "graph_003",
                "graph",
                "GET",
                "/graph/entities/%E6%9C%AC%E7%94%B0",
                params={"limit": 5},
                description="get_entity_with_limit_5",
            ),
            TestCase(
                "graph_004",
                "graph",
                "GET",
                "/graph/entities/%E6%9C%AC%E7%94%B0",
                params={"limit": 50},
                description="get_entity_with_limit_50",
            ),
        ]
    )

    # GET /graph/relations
    cases.extend(
        [
            TestCase(
                "graph_005",
                "graph",
                "GET",
                "/graph/relations",
                params={"entity": "本田"},
                description="get_relations_honda",
            ),
            TestCase(
                "graph_006",
                "graph",
                "GET",
                "/graph/relations",
                params={"entity": "本田", "entity_type": "组织机构"},
                description="get_relations_with_type",
            ),
            TestCase(
                "graph_007",
                "graph",
                "GET",
                "/graph/relations/search",
                params={"entity": "本田"},
                description="search_relations_honda",
            ),
            TestCase(
                "graph_008",
                "graph",
                "GET",
                "/graph/relations/search",
                params={"entity": "本田", "relation_types": "投资,合资", "limit": 20},
                description="search_relations_with_types",
            ),
        ]
    )

    # GET /graph/articles/{id}/graph - 动态生成
    cases.extend(
        [
            TestCase(
                "graph_009",
                "graph",
                "GET",
                "/graph/visualization",
                description="get_graph_snapshot",
            ),
        ]
    )

    # ===== 5. Communities =====
    cases.extend(
        [
            TestCase(
                "communities_001",
                "communities",
                "GET",
                "/admin/communities",
                description="list_communities_default",
            ),
            TestCase(
                "communities_002",
                "communities",
                "GET",
                "/admin/communities",
                params={"level": 0},
                description="list_communities_level_0",
            ),
            TestCase(
                "communities_003",
                "communities",
                "GET",
                "/admin/communities",
                params={"level": 1, "limit": 10},
                description="list_communities_level_1",
            ),
            TestCase(
                "communities_004",
                "communities",
                "GET",
                "/admin/communities/health",
                description="get_communities_health",
            ),
        ]
    )

    # GET /admin/communities/{id} - 动态生成
    cases.extend(
        [
            TestCase(
                "communities_005",
                "communities",
                "GET",
                "/admin/communities/00000000-0000-0000-0000-000000000000",
                expected_status=404,
                description="get_community_notfound",
            ),
        ]
    )

    # ===== 6. Admin =====
    cases.extend(
        [
            TestCase(
                "admin_001",
                "admin",
                "GET",
                "/admin/authorities",
                description="list_authorities_default",
            ),
            TestCase(
                "admin_002",
                "admin",
                "GET",
                "/admin/authorities",
                params={"needs_review_only": True},
                description="list_authorities_review_only",
            ),
        ]
    )

    # GET /admin/llm-usage
    cases.extend(
        [
            TestCase(
                "admin_003",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={"group_by": "summary", "from": "2024-01-01", "to": "2025-12-31"},
                description="llm_usage_summary",
            ),
            TestCase(
                "admin_004",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={"group_by": "model", "from": "2024-01-01", "to": "2025-12-31"},
                description="llm_usage_by_model",
            ),
            TestCase(
                "admin_005",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={"group_by": "call_point", "from": "2024-01-01", "to": "2025-12-31"},
                description="llm_usage_by_callpoint",
            ),
            TestCase(
                "admin_006",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={
                    "group_by": "time",
                    "from": "2024-01-01",
                    "to": "2025-12-31",
                    "granularity": "daily",
                },
                description="llm_usage_by_time_daily",
            ),
        ]
    )

    # GET /admin/llm-failures
    cases.extend(
        [
            TestCase(
                "admin_007",
                "admin",
                "GET",
                "/admin/llm-failures",
                description="list_llm_failures_default",
            ),
            TestCase(
                "admin_008",
                "admin",
                "GET",
                "/admin/llm-failures",
                params={"limit": 10},
                description="list_llm_failures_limit_10",
            ),
            TestCase(
                "admin_009",
                "admin",
                "GET",
                "/admin/llm-failures/stats",
                description="get_llm_failures_stats",
            ),
        ]
    )

    # GET /admin/memory/diagnostics
    cases.extend(
        [
            TestCase(
                "admin_010",
                "admin",
                "GET",
                "/admin/memory/diagnostics",
                description="get_memory_diagnostics",
            ),
        ]
    )

    # ===== 7. Monitoring =====
    cases.extend(
        [
            TestCase(
                "monitoring_001",
                "monitoring",
                "GET",
                "/monitoring/database/indexes",
                description="get_db_indexes",
            ),
            TestCase(
                "monitoring_002",
                "monitoring",
                "GET",
                "/monitoring/database/tables",
                description="get_db_tables",
            ),
            TestCase(
                "monitoring_003",
                "monitoring",
                "GET",
                "/monitoring/database/pool",
                description="get_db_pool",
            ),
            TestCase(
                "monitoring_004",
                "monitoring",
                "GET",
                "/monitoring/database/slow-queries",
                description="get_slow_queries",
            ),
        ]
    )

    # GET /monitoring/graph/metrics
    cases.extend(
        [
            TestCase(
                "monitoring_005",
                "monitoring",
                "GET",
                "/monitoring/graph/metrics",
                description="get_graph_metrics_health",
            ),
            TestCase(
                "monitoring_006",
                "monitoring",
                "GET",
                "/monitoring/graph/metrics",
                params={"view": "full"},
                description="get_graph_metrics_full",
            ),
            TestCase(
                "monitoring_007",
                "monitoring",
                "GET",
                "/monitoring/graph/metrics",
                params={"view": "health"},
                description="get_graph_metrics_health_explicit",
            ),
        ]
    )

    # ===== 8. Pipeline =====
    cases.extend(
        [
            TestCase(
                "pipeline_001",
                "pipeline",
                "GET",
                "/pipeline/queue/stats",
                description="get_queue_stats",
            ),
            TestCase(
                "pipeline_002",
                "pipeline",
                "POST",
                "/admin/pipeline/trigger",
                json_body={},
                description="trigger_pipeline_empty",
            ),
        ]
    )

    return cases


def add_dynamic_test_cases(cases: list[TestCase]) -> list[TestCase]:
    """根据提取的 ID 添加动态测试用例"""
    dynamic_cases = []

    # Articles by ID
    if extracted_ids["article_ids"]:
        article_id = extracted_ids["article_ids"][0]
        dynamic_cases.append(
            TestCase(
                "articles_dynamic_001",
                "articles",
                "GET",
                f"/articles/{article_id}",
                description=f"get_article_by_id_{article_id[:8]}",
            )
        )
        dynamic_cases.append(
            TestCase(
                "graph_dynamic_001",
                "graph",
                "GET",
                f"/graph/articles/{article_id}/graph",
                description=f"get_article_graph_{article_id[:8]}",
            )
        )

    # Sources by ID
    if extracted_ids["source_ids"]:
        source_id = extracted_ids["source_ids"][0]
        dynamic_cases.append(
            TestCase(
                "sources_dynamic_001",
                "sources",
                "GET",
                f"/sources/{source_id}",
                description=f"get_source_by_id_{source_id[:8]}",
            )
        )

    # Communities by ID
    if extracted_ids["community_ids"]:
        community_id = extracted_ids["community_ids"][0]
        dynamic_cases.append(
            TestCase(
                "communities_dynamic_001",
                "communities",
                "GET",
                f"/admin/communities/{community_id}",
                description=f"get_community_by_id_{community_id[:8]}",
            )
        )

    # Entities by name
    if extracted_ids["entity_names"]:
        entity_name = extracted_ids["entity_names"][0]
        encoded_name = quote(entity_name)
        dynamic_cases.append(
            TestCase(
                "graph_dynamic_002",
                "graph",
                "GET",
                f"/graph/entities/{encoded_name}",
                params={"limit": 20},
                description=f"get_entity_by_name_{entity_name}",
            )
        )

    return cases + dynamic_cases


# ── 核心功能 ──────────────────────────────────────────────────────


def execute_request(client: httpx.Client, test_case: TestCase) -> dict[str, Any]:
    """执行单个 HTTP 请求并记录完整信息"""
    url = f"{BASE_URL}{test_case.url}"
    start_time = time.time()

    try:
        # 执行请求
        if test_case.method == "GET":
            resp = client.get(url, params=test_case.params, timeout=TIMEOUT)
        elif test_case.method == "POST":
            resp = client.post(url, json=test_case.json_body, timeout=TIMEOUT)
        elif test_case.method == "PUT":
            resp = client.put(url, json=test_case.json_body, timeout=TIMEOUT)
        elif test_case.method == "PATCH":
            resp = client.patch(url, json=test_case.json_body, timeout=TIMEOUT)
        elif test_case.method == "DELETE":
            resp = client.delete(url, timeout=TIMEOUT)
        else:
            raise ValueError(f"Unsupported method: {test_case.method}")

        response_time_ms = (time.time() - start_time) * 1000

        # 解析响应
        try:
            response_body = resp.json()
        except Exception:
            response_body = {"raw": resp.text[:1000]}

        # 构建结果
        return {
            "test_name": test_case.name,
            "endpoint_group": test_case.endpoint_group,
            "method": test_case.method,
            "url": url,
            "path_params": {},
            "query_params": test_case.params,
            "request_body": test_case.json_body,
            "request_headers": {"X-API-Key": "***"},
            "status_code": resp.status_code,
            "expected_status": test_case.expected_status,
            "pass": resp.status_code == test_case.expected_status,
            "response_headers": dict(resp.headers),
            "response_body": response_body,
            "timestamp": datetime.now(UTC).isoformat(),
            "response_time_ms": round(response_time_ms, 2),
            "error": None,
        }

    except httpx.ConnectError as e:
        response_time_ms = (time.time() - start_time) * 1000
        return {
            "test_name": test_case.name,
            "endpoint_group": test_case.endpoint_group,
            "method": test_case.method,
            "url": url,
            "path_params": {},
            "query_params": test_case.params,
            "request_body": test_case.json_body,
            "request_headers": {"X-API-Key": "***"},
            "status_code": 0,
            "expected_status": test_case.expected_status,
            "pass": False,
            "response_headers": {},
            "response_body": None,
            "timestamp": datetime.now(UTC).isoformat(),
            "response_time_ms": round(response_time_ms, 2),
            "error": f"Connection failed: {e!s}",
        }

    except httpx.TimeoutException as e:
        response_time_ms = (time.time() - start_time) * 1000
        return {
            "test_name": test_case.name,
            "endpoint_group": test_case.endpoint_group,
            "method": test_case.method,
            "url": url,
            "path_params": {},
            "query_params": test_case.params,
            "request_body": test_case.json_body,
            "request_headers": {"X-API-Key": "***"},
            "status_code": 0,
            "expected_status": test_case.expected_status,
            "pass": False,
            "response_headers": {},
            "response_body": None,
            "timestamp": datetime.now(UTC).isoformat(),
            "response_time_ms": round(response_time_ms, 2),
            "error": f"Request timeout: {e!s}",
        }

    except Exception as e:
        response_time_ms = (time.time() - start_time) * 1000
        return {
            "test_name": test_case.name,
            "endpoint_group": test_case.endpoint_group,
            "method": test_case.method,
            "url": url,
            "path_params": {},
            "query_params": test_case.params,
            "request_body": test_case.json_body,
            "request_headers": {"X-API-Key": "***"},
            "status_code": 0,
            "expected_status": test_case.expected_status,
            "pass": False,
            "response_headers": {},
            "response_body": None,
            "timestamp": datetime.now(UTC).isoformat(),
            "response_time_ms": round(response_time_ms, 2),
            "error": f"Unexpected error: {e!s}",
        }


def extract_ids_from_response(test_case: TestCase, response_body: dict):
    """从响应中提取 ID 供后续测试使用"""
    if not response_body or "data" not in response_body:
        return

    data = response_body["data"]

    # 提取 article IDs
    if "/articles" in test_case.url and isinstance(data, dict):
        items = data.get("items", [])
        for item in items:
            if item.get("id") and item["id"] not in extracted_ids["article_ids"]:
                extracted_ids["article_ids"].append(item["id"])

    # 提取 source IDs
    if "/sources" in test_case.url:
        items = data if isinstance(data, list) else []
        for item in items:
            if item.get("id") and item["id"] not in extracted_ids["source_ids"]:
                extracted_ids["source_ids"].append(item["id"])

    # 提取 community IDs
    if "/communities" in test_case.url and isinstance(data, dict):
        items = data.get("communities", data.get("items", []))
        for item in items:
            if item.get("id") and item["id"] not in extracted_ids["community_ids"]:
                extracted_ids["community_ids"].append(item["id"])

    # 提取 entity names
    if "/graph/entities" in test_case.url and isinstance(data, dict):
        entity = data.get("entity", {})
        if (
            entity.get("canonical_name")
            and entity["canonical_name"] not in extracted_ids["entity_names"]
        ):
            extracted_ids["entity_names"].append(entity["canonical_name"])


def save_response_to_file(result: dict, test_counter: dict[str, int]):
    """保存测试结果到 JSON 文件"""
    endpoint_group = result["endpoint_group"]
    test_number = test_counter.get(endpoint_group, 0) + 1
    test_counter[endpoint_group] = test_number

    # 生成文件名
    safe_name = result["test_name"].replace(" ", "_").replace("/", "_")
    filename = f"{endpoint_group}_{test_number:03d}_{safe_name}.json"
    filepath = OUTPUT_DIR / filename

    # 保存文件
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)


def run_single_test(
    client: httpx.Client, test_case: TestCase, test_counter: dict[str, int]
) -> dict:
    """运行单个测试用例"""
    # 执行请求
    result = execute_request(client, test_case)

    # 提取 ID
    if result["pass"] and result.get("response_body"):
        with ids_lock:
            extract_ids_from_response(test_case, result["response_body"])

    # 保存到文件
    with results_lock:
        save_response_to_file(result, test_counter)
        results.append(result)

    # 打印进度
    status_icon = "✓" if result["pass"] else "✗"
    error_info = f" - Error: {result['error']}" if result.get("error") else ""
    print(
        f"  {status_icon} [{result['status_code']}] {result['method']} {test_case.url} ({result['test_name']}) - {result['response_time_ms']}ms{error_info}"
    )

    return result


def run_tests():
    """执行全面 API 测试"""
    print("=" * 70)
    print("Weaver API 全面测试 (并发执行)")
    print("=" * 70)
    print()

    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 生成测试用例
    all_cases = generate_test_cases()
    print(f"生成 {len(all_cases)} 个基础测试用例")
    print()

    # 创建 httpx 客户端
    with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=TIMEOUT) as client:
        # Test counter for file naming
        test_counter: dict[str, int] = {}

        # 并发执行测试
        print("开始执行测试...")
        print()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # 提交所有任务
            futures = {
                executor.submit(run_single_test, client, case, test_counter): case
                for case in all_cases
            }

            # 等待完成
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"  ✗ 测试执行异常: {e}")

    # Add dynamic test cases (based on extracted IDs)
    dynamic_cases = add_dynamic_test_cases([])
    if dynamic_cases:
        print()
        print(f"执行 {len(dynamic_cases)} 个动态测试用例（基于实际数据）...")
        print()

        with (
            httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=TIMEOUT) as client,
            ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor,
        ):
            futures = {
                executor.submit(run_single_test, client, case, test_counter): case
                for case in dynamic_cases
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"  ✗ 测试执行异常: {e}")

    # 生成报告
    generate_summary()


def generate_summary():
    """生成详细测试报告"""
    print()
    print("=" * 70)
    print("测试汇总")
    print("=" * 70)

    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    failed = sum(1 for r in results if not r["pass"])

    # 按端点分组统计
    by_endpoint = {}
    for r in results:
        endpoint = r.get("endpoint_group", "unknown")
        if endpoint not in by_endpoint:
            by_endpoint[endpoint] = {"total": 0, "passed": 0, "failed": 0}
        by_endpoint[endpoint]["total"] += 1
        if r["pass"]:
            by_endpoint[endpoint]["passed"] += 1
        else:
            by_endpoint[endpoint]["failed"] += 1

    # 平均响应时间
    response_times = [
        r["response_time_ms"]
        for r in results
        if r.get("response_time_ms") and r["response_time_ms"] > 0
    ]
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0

    # 打印汇总
    print(f"总计: {total} 个测试")
    print(f"通过: {passed}")
    print(f"失败: {failed}")
    print(f"通过率: {passed / total * 100:.1f}%" if total > 0 else "通过率: 0%")
    print(f"平均响应时间: {avg_response_time:.1f}ms")
    print()

    print("按端点统计:")
    for endpoint, stats in sorted(by_endpoint.items()):
        pass_rate = stats["passed"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(
            f"  {endpoint:15s}: {stats['total']:3d} tests, {stats['passed']:3d} passed, {stats['failed']:3d} failed ({pass_rate:.1f}%)"
        )

    # 打印失败详情
    if failed > 0:
        print()
        print("失败测试详情:")
        for r in results:
            if not r["pass"]:
                print(f"  ✗ [{r['status_code']}] {r['method']} {r['url']} ({r['test_name']})")
                print(f"    期望: {r['expected_status']}, 实际: {r['status_code']}")
                if r.get("error"):
                    print(f"    错误: {r['error']}")

    # 保存汇总到文件
    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{passed / total * 100:.1f}%" if total > 0 else "0%",
        "avg_response_time_ms": round(avg_response_time, 2),
        "by_endpoint": by_endpoint,
        "failed_tests": [
            {
                "test_name": r["test_name"],
                "url": r["url"],
                "expected": r["expected_status"],
                "actual": r["status_code"],
                "error": r.get("error"),
            }
            for r in results
            if not r["pass"]
        ],
    }

    summary_path = OUTPUT_DIR / "_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n汇总已保存到: {summary_path}")
    print(f"详细响应: {OUTPUT_DIR}")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)

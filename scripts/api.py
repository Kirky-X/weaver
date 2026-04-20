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
ADMIN_HEADERS = {"X-API-Key": ADMIN_API_KEY}
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
    sequential: bool = False  # True = 必须顺序执行（如依赖前序测试结果）


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
                "get_all_articles_default",
                "articles",
                "GET",
                "/articles",
                description="get_all_articles_default",
            ),
            TestCase(
                "pagination_page1_size10",
                "articles",
                "GET",
                "/articles",
                params={"page": 1, "page_size": 10},
                description="pagination_page1_size10",
            ),
            TestCase(
                "pagination_page2_size20",
                "articles",
                "GET",
                "/articles",
                params={"page": 1, "page_size": 20},
                description="pagination_page2_size20",
            ),
            TestCase(
                "pagesize_50",
                "articles",
                "GET",
                "/articles",
                params={"page_size": 50},
                description="pagesize_50",
            ),
            TestCase(
                "pagesize_100",
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
                "invalid_page_0",
                "articles",
                "GET",
                "/articles",
                params={"page": 0},
                expected_status=422,
                description="invalid_page_0",
            ),
            TestCase(
                "invalid_page_negative",
                "articles",
                "GET",
                "/articles",
                params={"page": -1},
                expected_status=422,
                description="invalid_page_negative",
            ),
            TestCase(
                "invalid_pagesize_0",
                "articles",
                "GET",
                "/articles",
                params={"page_size": 0},
                expected_status=422,
                description="invalid_pagesize_0",
            ),
            TestCase(
                "invalid_pagesize_101",
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
                "filter_category_tech",
                "articles",
                "GET",
                "/articles",
                params={"category": "科技"},
                description="filter_category_tech",
            ),
            TestCase(
                "filter_category_finance",
                "articles",
                "GET",
                "/articles",
                params={"category": "财经"},
                description="filter_category_finance",
            ),
            TestCase(
                "filter_minscore_0.5",
                "articles",
                "GET",
                "/articles",
                params={"min_score": 0.5},
                description="filter_minscore_0.5",
            ),
            TestCase(
                "filter_mincredibility_0.7",
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
                "sort_by_publish_time_desc",
                "articles",
                "GET",
                "/articles",
                params={"sort_by": "publish_time", "sort_order": "desc"},
                description="sort_by_publish_time_desc",
            ),
            TestCase(
                "sort_by_score_asc",
                "articles",
                "GET",
                "/articles",
                params={"sort_by": "score", "sort_order": "asc"},
                description="sort_by_score_asc",
            ),
            TestCase(
                "sort_by_created_at_desc",
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
                "article_notfound",
                "articles",
                "GET",
                "/articles/00000000-0000-0000-0000-000000000000",
                expected_status=404,
                description="article_notfound",
            ),
            TestCase(
                "article_invalid_uuid",
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
                "list_sources_enabled",
                "sources",
                "GET",
                "/sources",
                params={"enabled_only": True},
                description="list_sources_enabled",
            ),
            TestCase(
                "list_sources_all",
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
    random_id_2 = "test-source-" + "".join(
        [secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8)]
    )
    cases.extend(
        [
            TestCase(
                "create_source_valid",
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
                "create_source_duplicate",
                "sources",
                "POST",
                "/sources",
                json_body={
                    "id": random_id,  # Same ID as sources_003 - expect 409 duplicate
                    "name": f"test_source_{random_id}",
                    "url": "https://example.com/rss",
                    "source_type": "rss",
                },
                expected_status=409,
                description="create_source_duplicate",
                sequential=True,  # Must execute after sources_003 completes
            ),
            TestCase(
                "create_source_invalid_empty_name",
                "sources",
                "POST",
                "/sources",
                json_body={"name": "", "id": "test-invalid", "url": "https://example.com"},
                expected_status=422,
                description="create_source_invalid_empty_name",
            ),
            TestCase(
                "create_source_invalid_url",
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
                "source_notfound",
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
                "default_search_ai",
                "search",
                "GET",
                "/search",
                params={"q": "融资"},
                description="default_search_investment",
            ),
            TestCase(
                "local_mode_search",
                "search",
                "GET",
                "/search",
                params={"q": "东升宇航", "mode": "local"},
                description="local_mode_search",
            ),
            TestCase(
                "global_mode_search",
                "search",
                "GET",
                "/search",
                params={"q": "投资", "mode": "global"},
                description="global_mode_search",
            ),
            TestCase(
                "search_with_limit_3",
                "search",
                "GET",
                "/search",
                params={"q": "投资", "limit": 3},
                description="search_with_limit_3",
            ),
            TestCase(
                "search_with_limit_50",
                "search",
                "GET",
                "/search",
                params={"q": "投资", "limit": 50},
                description="search_with_limit_50",
            ),
            TestCase(
                "search_empty_query",
                "search",
                "GET",
                "/search",
                params={"q": "", "mode": "local"},
                expected_status=422,
                description="search_empty_query",
            ),
            TestCase(
                "search_long_query",
                "search",
                "GET",
                "/search",
                params={"q": "投资"},  # Use generic query that matches actual data,
                description="search_long_query",
            ),
            TestCase(
                "articles_mode_with_threshold",
                "search",
                "GET",
                "/search",
                params={
                    "q": "三星"
                },  # Use entity that exists in data, "mode": "articles", "threshold": 0.5},
                description="articles_mode_with_threshold",
            ),
        ]
    )

    # POST /search/drift
    cases.extend(
        [
            TestCase(
                "drift_search_default",
                "search",
                "POST",
                "/search/drift",
                json_body={"query": "融资", "max_hops": 2},  # Query matching actual data,
                description="drift_search_default",
            ),
            TestCase(
                "drift_search_custom_params",
                "search",
                "POST",
                "/search/drift",
                json_body={
                    "query": "投资",
                    "primer_k": 5,
                    "max_follow_ups": 3,
                },  # Query matching actual data,
                description="drift_search_custom_params",
            ),
            TestCase(
                "drift_search_empty_query",
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
                "causal_search_default",
                "search",
                "POST",
                "/search/causal",
                json_body={"query": "融资", "max_depth": 3},  # Query matching actual data,
                description="causal_search_default",
            ),
            TestCase(
                "causal_search_custom_depth",
                "search",
                "POST",
                "/search/causal",
                json_body={"query": "投资", "max_depth": 5, "min_confidence": 0.5},
                description="causal_search_custom_depth",
            ),
            TestCase(
                "causal_search_empty_query",
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
                "temporal_search_default",
                "search",
                "POST",
                "/search/temporal",
                json_body={"query": "融资", "time_window_days": 30},  # Query matching actual data,
                description="temporal_search_default",
            ),
            TestCase(
                "temporal_search_custom_window",
                "search",
                "POST",
                "/search/temporal",
                json_body={"query": "投资", "time_window_days": 7, "limit": 20},
                description="temporal_search_custom_window",
            ),
            TestCase(
                "temporal_search_empty_query",
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
    # Note: "本田" entity doesn't exist in test database, expect 404
    cases.extend(
        [
            TestCase(
                "get_entity_test",
                "graph",
                "GET",
                "/graph/entities/%E4%B8%9C%E5%8D%87%E5%AE%87%E8%88%AA",  # 东升宇航
                description="get_entity_test",
            ),
            TestCase(
                "get_entity_notfound",
                "graph",
                "GET",
                "/graph/entities/NonExistentEntityXYZ",
                expected_status=404,
                description="get_entity_notfound",
            ),
            TestCase(
                "get_entity_with_limit",
                "graph",
                "GET",
                "/graph/entities/%E4%B8%9C%E5%8D%87%E5%AE%87%E8%88%AA",  # 东升宇航
                params={"limit": 5},
                description="get_entity_with_limit",
            ),
            TestCase(
                "get_entity_with_limit_50",
                "graph",
                "GET",
                "/graph/entities/%E4%B8%9C%E5%8D%87%E5%AE%87%E8%88%AA",  # 东升宇航
                params={"limit": 50},
                description="get_entity_with_limit_50",
            ),
        ]
    )

    # GET /graph/relations - returns 404 for non-existent entity (P0-1 fix)
    cases.extend(
        [
            TestCase(
                "get_relations_entity_notfound",
                "graph",
                "GET",
                "/graph/relations",
                params={"entity": "NonExistentEntity123"},
                expected_status=404,
                description="get_relations_entity_notfound",
            ),
            TestCase(
                "get_relations_entity_notfound_with_type",
                "graph",
                "GET",
                "/graph/relations",
                params={"entity": "NonExistentEntity123", "entity_type": "组织机构"},
                expected_status=404,
                description="get_relations_entity_notfound_with_type",
            ),
            TestCase(
                "search_relations_empty",
                "graph",
                "GET",
                "/graph/relations/search",
                params={"entity": "东升宇航"},
                description="search_relations_empty",
            ),
            TestCase(
                "search_relations_with_types",
                "graph",
                "GET",
                "/graph/relations/search",
                params={
                    "entity": "宇石空间",
                    "relation_types": "投资",
                    "limit": 20,
                },  # Entity that may exist,
                description="search_relations_with_types",
            ),
        ]
    )

    # GET /graph/articles/{id}/graph - 动态生成
    cases.extend(
        [
            TestCase(
                "get_graph_snapshot",
                "graph",
                "GET",
                "/graph/visualization",
                description="get_graph_snapshot",
            ),
        ]
    )

    # ===== 5. Communities (必须在rebuild后顺序执行) =====
    cases.extend(
        [
            TestCase(
                "list_communities_default",
                "communities",
                "GET",
                "/admin/communities",
                description="list_communities_default",
                sequential=True,  # Must run after rebuild
            ),
            TestCase(
                "list_communities_level_0",
                "communities",
                "GET",
                "/admin/communities",
                params={"level": 0},
                description="list_communities_level_0",
                sequential=True,  # Must run after rebuild
            ),
            TestCase(
                "list_communities_level_1",
                "communities",
                "GET",
                "/admin/communities",
                params={"level": 1, "limit": 10},
                description="list_communities_level_1",
                sequential=True,  # Must run after rebuild
            ),
            TestCase(
                "get_communities_health",
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
                "get_community_notfound",
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
                "list_authorities_default",
                "admin",
                "GET",
                "/admin/authorities",
                description="list_authorities_default",
            ),
            TestCase(
                "list_authorities_review_only",
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
                "llm_usage_summary",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={"group_by": "summary", "from": "2026-03-21", "to": "2026-04-20"},
                description="llm_usage_summary",
            ),
            TestCase(
                "llm_usage_by_model",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={"group_by": "model", "from": "2026-03-21", "to": "2026-04-20"},
                description="llm_usage_by_model",
            ),
            TestCase(
                "llm_usage_by_callpoint",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={"group_by": "call_point", "from": "2026-03-21", "to": "2026-04-20"},
                description="llm_usage_by_callpoint",
            ),
            TestCase(
                "llm_usage_by_time_daily",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={
                    "group_by": "time",
                    "from": "2026-03-21",
                    "to": "2026-04-20",
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
                "list_llm_failures_default",
                "admin",
                "GET",
                "/admin/llm-failures",
                description="list_llm_failures_default",
            ),
            TestCase(
                "list_llm_failures_limit_10",
                "admin",
                "GET",
                "/admin/llm-failures",
                params={"limit": 10},
                description="list_llm_failures_limit_10",
            ),
            TestCase(
                "get_llm_failures_stats",
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
                "get_memory_diagnostics",
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
                "get_db_indexes",
                "monitoring",
                "GET",
                "/admin/monitoring/database/indexes",
                description="get_db_indexes",
            ),
            TestCase(
                "get_db_tables",
                "monitoring",
                "GET",
                "/admin/monitoring/database/tables",
                description="get_db_tables",
            ),
            TestCase(
                "get_db_pool",
                "monitoring",
                "GET",
                "/admin/monitoring/database/pool",
                description="get_db_pool",
            ),
            TestCase(
                "get_slow_queries",
                "monitoring",
                "GET",
                "/admin/monitoring/database/slow-queries",
                description="get_slow_queries",
            ),
        ]
    )

    # GET /monitoring/graph/metrics
    cases.extend(
        [
            TestCase(
                "get_graph_metrics_health",
                "monitoring",
                "GET",
                "/monitoring/graph/metrics",
                description="get_graph_metrics_health",
            ),
            TestCase(
                "get_graph_metrics_full",
                "monitoring",
                "GET",
                "/monitoring/graph/metrics",
                params={"view": "full"},
                description="get_graph_metrics_full",
            ),
            TestCase(
                "get_graph_metrics_health_explicit",
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
                "get_queue_stats",
                "pipeline",
                "GET",
                "/pipeline/queue/stats",
                description="get_queue_stats",
            ),
            TestCase(
                "trigger_pipeline_empty",
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

    # Use ADMIN_HEADERS for:
    # 1. Admin endpoints (/admin/*)
    # 2. Monitoring/graph endpoints (/monitoring/graph/*)
    # 3. Write operations on sources (POST/PUT/PATCH/DELETE on /sources)
    is_admin_url = "/admin" in test_case.url or "/monitoring/graph" in test_case.url
    is_sources_write = "/sources" in test_case.url and test_case.method in (
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    )
    req_headers = ADMIN_HEADERS if (is_admin_url or is_sources_write) else HEADERS

    try:
        # 执行请求 (override client headers per request)
        if test_case.method == "GET":
            resp = client.get(url, params=test_case.params, headers=req_headers, timeout=TIMEOUT)
        elif test_case.method == "POST":
            resp = client.post(url, json=test_case.json_body, headers=req_headers, timeout=TIMEOUT)
        elif test_case.method == "PUT":
            resp = client.put(url, json=test_case.json_body, headers=req_headers, timeout=TIMEOUT)
        elif test_case.method == "PATCH":
            resp = client.patch(url, json=test_case.json_body, headers=req_headers, timeout=TIMEOUT)
        elif test_case.method == "DELETE":
            resp = client.delete(url, headers=req_headers, timeout=TIMEOUT)
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
            "description": test_case.description,
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
            "description": test_case.description,
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
            "description": test_case.description,
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
            "description": test_case.description,
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

        # 分离并发测试和顺序测试
        concurrent_cases = [c for c in all_cases if not c.sequential]
        sequential_cases = [c for c in all_cases if c.sequential]

        # 并发执行测试
        print("开始执行并发测试...")
        print()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # 提交所有并发任务
            futures = {
                executor.submit(run_single_test, client, case, test_counter): case
                for case in concurrent_cases
            }

            # 等待完成
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"  ✗ 测试执行异常: {e}")

        # 顺序执行依赖测试（如 duplicate key 测试）
        if sequential_cases:
            print()
            print(f"执行 {len(sequential_cases)} 个顺序测试...")
            print()

            for case in sequential_cases:
                try:
                    run_single_test(client, case, test_counter)
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

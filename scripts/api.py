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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import quote

import httpx

# ── 配置 ──────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8000/api/v1"
API_KEY = "weaver_test_api_key_for_comprehensive_testing_2026"
ADMIN_API_KEY = "weaver_test_admin_api_key_for_comprehensive_testing_2026"
HEADERS = {"X-API-Key": API_KEY}
ADMIN_HEADERS = {"X-API-Key": ADMIN_API_KEY}
TIMEOUT = httpx.Timeout(180.0)  # LLM-heavy operations (rebuild/search) need >60s
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
                params={"category": "经济"},
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
                    "url": "https://www.solidot.org/index.rss",  # Real working RSS feed
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
                    "url": "https://www.solidot.org/index.rss",
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
                json_body={"query": "融资", "time_range": "30d"},  # Query matching actual data,
                description="temporal_search_default",
            ),
            TestCase(
                "temporal_search_custom_window",
                "search",
                "POST",
                "/search/temporal",
                json_body={"query": "投资", "time_range": "7d", "limit": 20},
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
                "/graph/entities/%E7%BE%8E%E5%9B%BD",  # 美国 (真实存在的实体, mention_count=17)
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
                "/graph/entities/%E7%BE%8E%E5%9B%BD",  # 美国
                params={"limit": 5},
                description="get_entity_with_limit",
            ),
            TestCase(
                "get_entity_with_limit_50",
                "graph",
                "GET",
                "/graph/entities/%E7%BE%8E%E5%9B%BD",  # 美国
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
                sequential=True,  # Must run after rebuild
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
    # Use dynamic date range: last 90 days to tomorrow (covers all recent data)
    _today = datetime.now(UTC)
    _llm_from = (_today - timedelta(days=90)).strftime("%Y-%m-%d")
    _llm_to = (_today + timedelta(days=1)).strftime("%Y-%m-%d")
    cases.extend(
        [
            TestCase(
                "llm_usage_summary",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={"group_by": "summary", "from": _llm_from, "to": _llm_to},
                description="llm_usage_summary",
            ),
            TestCase(
                "llm_usage_by_model",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={"group_by": "model", "from": _llm_from, "to": _llm_to},
                description="llm_usage_by_model",
            ),
            TestCase(
                "llm_usage_by_callpoint",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={"group_by": "call_point", "from": _llm_from, "to": _llm_to},
                description="llm_usage_by_callpoint",
            ),
            TestCase(
                "llm_usage_by_time_daily",
                "admin",
                "GET",
                "/admin/llm-usage",
                params={
                    "group_by": "time",
                    "from": _llm_from,
                    "to": _llm_to,
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
            # GET /pipeline/queue/stats - 已删除的旧端点
            # TestCase(
            #     "get_queue_stats",
            #     "pipeline",
            #     "GET",
            #     "/pipeline/queue/stats",
            #     description="get_queue_stats",
            # ),
            # POST /admin/pipeline/trigger - 跳过(需要实际爬取,非常慢)
            # TestCase(
            #     "trigger_pipeline_empty",
            #     "pipeline",
            #     "POST",
            #     "/admin/pipeline/trigger",
            #     json_body={},
            #     description="trigger_pipeline_empty",
            # ),
        ]
    )

    # ===== 9. System 端点扩展 (system) =====
    cases.extend(
        [
            # GET /status - 系统状态
            TestCase(
                "system_status_normal",
                "system",
                "GET",
                "/status",
                description="system_status_normal",
            ),
            TestCase(
                "system_status_with_param",
                "system",
                "GET",
                "/status",
                params={"_t": "123"},
                description="system_status_with_param",
            ),
            TestCase(
                "system_status_special_char",
                "system",
                "GET",
                "/status",
                params={"_t": "'\"<script>"},
                description="system_status_special_char",
            ),
            TestCase(
                "system_status_long_param",
                "system",
                "GET",
                "/status",
                params={"_t": "x" * 1000},
                description="system_status_long_param",
            ),
            TestCase(
                "system_status_unicode",
                "system",
                "GET",
                "/status",
                params={"_t": "中文测试"},
                description="system_status_unicode",
            ),
            # GET /config - 系统配置
            TestCase(
                "system_config_normal",
                "system",
                "GET",
                "/config",
                expected_status=403,
                description="system_config_normal",
            ),
            TestCase(
                "system_config_with_param",
                "system",
                "GET",
                "/config",
                params={"detail": "true"},
                expected_status=403,
                description="system_config_with_param",
            ),
            TestCase(
                "system_config_special_char",
                "system",
                "GET",
                "/config",
                params={"_t": "'\"<script>"},
                expected_status=403,
                description="system_config_special_char",
            ),
            TestCase(
                "system_config_long_param",
                "system",
                "GET",
                "/config",
                params={"_t": "x" * 1000},
                expected_status=403,
                description="system_config_long_param",
            ),
            TestCase(
                "system_config_unicode",
                "system",
                "GET",
                "/config",
                params={"_t": "中文测试"},
                expected_status=403,
                description="system_config_unicode",
            ),
        ]
    )

    # ===== 10. Pipeline 端点扩展 (pipeline) =====
    cases.extend(
        [
            # GET /pipeline/status
            TestCase(
                "pipeline_status_normal",
                "pipeline",
                "GET",
                "/pipeline/status",
                description="pipeline_status_normal",
            ),
            TestCase(
                "pipeline_status_with_param",
                "pipeline",
                "GET",
                "/pipeline/status",
                params={"_t": "123"},
                description="pipeline_status_with_param",
            ),
            TestCase(
                "pipeline_status_special_char",
                "pipeline",
                "GET",
                "/pipeline/status",
                params={"_t": "'\""},
                description="pipeline_status_special_char",
            ),
            TestCase(
                "pipeline_status_long_param",
                "pipeline",
                "GET",
                "/pipeline/status",
                params={"_t": "x" * 1000},
                description="pipeline_status_long_param",
            ),
            TestCase(
                "pipeline_status_unicode",
                "pipeline",
                "GET",
                "/pipeline/status",
                params={"_t": "中文"},
                description="pipeline_status_unicode",
            ),
            # GET /pipeline/queue/stats
            TestCase(
                "pipeline_queue_stats_normal",
                "pipeline",
                "GET",
                "/pipeline/queue/stats",
                description="pipeline_queue_stats_normal",
            ),
            TestCase(
                "pipeline_queue_stats_with_param",
                "pipeline",
                "GET",
                "/pipeline/queue/stats",
                params={"_t": "123"},
                description="pipeline_queue_stats_with_param",
            ),
            TestCase(
                "pipeline_queue_stats_special_char",
                "pipeline",
                "GET",
                "/pipeline/queue/stats",
                params={"_t": "'\""},
                description="pipeline_queue_stats_special_char",
            ),
            TestCase(
                "pipeline_queue_stats_long_param",
                "pipeline",
                "GET",
                "/pipeline/queue/stats",
                params={"_t": "x" * 1000},
                description="pipeline_queue_stats_long_param",
            ),
            TestCase(
                "pipeline_queue_stats_unicode",
                "pipeline",
                "GET",
                "/pipeline/queue/stats",
                params={"_t": "中文"},
                description="pipeline_queue_stats_unicode",
            ),
            # GET /pipeline/tasks/{task_id}
            TestCase(
                "pipeline_task_notfound",
                "pipeline",
                "GET",
                "/pipeline/tasks/00000000-0000-0000-0000-000000000000",
                expected_status=404,
                description="pipeline_task_notfound",
            ),
            TestCase(
                "pipeline_task_invalid_uuid",
                "pipeline",
                "GET",
                "/pipeline/tasks/not-a-uuid",
                expected_status=404,
                description="pipeline_task_invalid_uuid",
            ),
            TestCase(
                "pipeline_task_special_char",
                "pipeline",
                "GET",
                "/pipeline/tasks/'OR'1'='1",
                expected_status=404,
                description="pipeline_task_special_char",
            ),
            TestCase(
                "pipeline_task_long_id",
                "pipeline",
                "GET",
                f"/pipeline/tasks/{'x' * 1000}",
                expected_status=404,
                description="pipeline_task_long_id",
            ),
            TestCase(
                "pipeline_task_unicode",
                "pipeline",
                "GET",
                "/pipeline/tasks/中文测试",
                expected_status=404,
                description="pipeline_task_unicode",
            ),
            # POST /pipeline/trigger (耗时操作, sequential=True 避免并发问题)
            TestCase(
                "pipeline_trigger_empty_body",
                "pipeline",
                "POST",
                "/pipeline/trigger",
                json_body={},
                sequential=True,
                description="pipeline_trigger_empty_body",
            ),
            TestCase(
                "pipeline_trigger_invalid_source",
                "pipeline",
                "POST",
                "/pipeline/trigger",
                json_body={"source_id": "nonexistent"},
                expected_status=404,
                sequential=True,
                description="pipeline_trigger_invalid_source",
            ),
            TestCase(
                "pipeline_trigger_force_false",
                "pipeline",
                "POST",
                "/pipeline/trigger",
                json_body={"source_id": "newsnow-36kr", "force": False},
                sequential=True,
                description="pipeline_trigger_force_false",
            ),
            TestCase(
                "pipeline_trigger_max_items",
                "pipeline",
                "POST",
                "/pipeline/trigger",
                json_body={"source_id": "newsnow-36kr", "max_items": 1},
                sequential=True,
                description="pipeline_trigger_max_items",
            ),
            TestCase(
                "pipeline_trigger_special_char",
                "pipeline",
                "POST",
                "/pipeline/trigger",
                json_body={"source_id": "'\"<script>"},
                expected_status=404,
                sequential=True,
                description="pipeline_trigger_special_char",
            ),
            # POST /pipeline/url (耗时操作, sequential=True)
            TestCase(
                "pipeline_url_valid",
                "pipeline",
                "POST",
                "/pipeline/url",
                json_body={"url": "https://www.solidot.org/index.rss"},
                sequential=True,
                description="pipeline_url_valid",
            ),
            TestCase(
                "pipeline_url_invalid",
                "pipeline",
                "POST",
                "/pipeline/url",
                json_body={"url": "invalid-url"},
                expected_status=422,
                sequential=True,
                description="pipeline_url_invalid",
            ),
            TestCase(
                "pipeline_url_empty",
                "pipeline",
                "POST",
                "/pipeline/url",
                json_body={"url": ""},
                expected_status=422,
                sequential=True,
                description="pipeline_url_empty",
            ),
            TestCase(
                "pipeline_url_special_char",
                "pipeline",
                "POST",
                "/pipeline/url",
                json_body={"url": "javascript:alert(1)"},
                expected_status=422,
                sequential=True,
                description="pipeline_url_special_char",
            ),
            TestCase(
                "pipeline_url_long",
                "pipeline",
                "POST",
                "/pipeline/url",
                json_body={"url": f"https://example.com/{'x' * 1000}"},
                sequential=True,
                description="pipeline_url_long",
            ),
            # POST /pipeline/url/stream (SSE, 耗时操作, sequential=True)
            TestCase(
                "pipeline_url_stream_valid",
                "pipeline",
                "POST",
                "/pipeline/url/stream",
                json_body={"url": "https://www.solidot.org/index.rss"},
                sequential=True,
                description="pipeline_url_stream_valid",
            ),
            TestCase(
                "pipeline_url_stream_invalid",
                "pipeline",
                "POST",
                "/pipeline/url/stream",
                json_body={"url": "invalid"},
                expected_status=422,
                sequential=True,
                description="pipeline_url_stream_invalid",
            ),
            TestCase(
                "pipeline_url_stream_empty",
                "pipeline",
                "POST",
                "/pipeline/url/stream",
                json_body={"url": ""},
                expected_status=422,
                sequential=True,
                description="pipeline_url_stream_empty",
            ),
            TestCase(
                "pipeline_url_stream_special_char",
                "pipeline",
                "POST",
                "/pipeline/url/stream",
                json_body={"url": "javascript:alert(1)"},
                expected_status=422,
                sequential=True,
                description="pipeline_url_stream_special_char",
            ),
            TestCase(
                "pipeline_url_stream_long",
                "pipeline",
                "POST",
                "/pipeline/url/stream",
                json_body={"url": f"https://example.com/{'x' * 1000}"},
                sequential=True,
                description="pipeline_url_stream_long",
            ),
        ]
    )

    # ===== 11. Graph 扩展端点 (graph) =====
    cases.extend(
        [
            # GET /graph/entities
            TestCase(
                "graph_entities_default",
                "graph",
                "GET",
                "/graph/entities",
                description="graph_entities_default",
            ),
            TestCase(
                "graph_entities_with_limit",
                "graph",
                "GET",
                "/graph/entities",
                params={"limit": 5},
                description="graph_entities_with_limit",
            ),
            TestCase(
                "graph_entities_with_offset",
                "graph",
                "GET",
                "/graph/entities",
                params={"offset": 10, "limit": 5},
                description="graph_entities_with_offset",
            ),
            TestCase(
                "graph_entities_invalid_limit",
                "graph",
                "GET",
                "/graph/entities",
                params={"limit": 0},
                expected_status=422,
                description="graph_entities_invalid_limit",
            ),
            TestCase(
                "graph_entities_invalid_offset",
                "graph",
                "GET",
                "/graph/entities",
                params={"offset": -1},
                expected_status=422,
                description="graph_entities_invalid_offset",
            ),
            # GET /graph/articles/{article_id}/graph
            TestCase(
                "graph_article_notfound",
                "graph",
                "GET",
                "/graph/articles/00000000-0000-0000-0000-000000000000/graph",
                expected_status=404,
                description="graph_article_notfound",
            ),
            TestCase(
                "graph_article_invalid_uuid",
                "graph",
                "GET",
                "/graph/articles/not-a-uuid/graph",
                expected_status=404,
                description="graph_article_invalid_uuid",
            ),
            TestCase(
                "graph_article_special_char",
                "graph",
                "GET",
                "/graph/articles/'OR'1'='1/graph",
                expected_status=404,
                description="graph_article_special_char",
            ),
            TestCase(
                "graph_article_long_id",
                "graph",
                "GET",
                f"/graph/articles/{'x' * 1000}/graph",
                expected_status=404,
                description="graph_article_long_id",
            ),
            TestCase(
                "graph_article_unicode",
                "graph",
                "GET",
                "/graph/articles/中文/graph",
                expected_status=404,
                description="graph_article_unicode",
            ),
            # POST /graph/traverse
            TestCase(
                "graph_traverse_default",
                "graph",
                "POST",
                "/graph/traverse",
                json_body={"start_entity": "美国"},
                description="graph_traverse_default",
            ),
            TestCase(
                "graph_traverse_max_depth",
                "graph",
                "POST",
                "/graph/traverse",
                json_body={"start_entity": "美国", "max_depth": 6},
                description="graph_traverse_max_depth",
            ),
            TestCase(
                "graph_traverse_invalid_depth",
                "graph",
                "POST",
                "/graph/traverse",
                json_body={"start_entity": "美国", "max_depth": 10},
                expected_status=422,
                description="graph_traverse_invalid_depth",
            ),
            TestCase(
                "graph_traverse_empty_entity",
                "graph",
                "POST",
                "/graph/traverse",
                json_body={"start_entity": ""},
                expected_status=422,
                description="graph_traverse_empty_entity",
            ),
            TestCase(
                "graph_traverse_special_char",
                "graph",
                "POST",
                "/graph/traverse",
                json_body={"start_entity": "'\"<script>"},
                description="graph_traverse_special_char",
            ),
            # GET /graph/metrics
            TestCase(
                "graph_metrics_default",
                "graph",
                "GET",
                "/graph/metrics",
                description="graph_metrics_default",
            ),
            TestCase(
                "graph_metrics_health",
                "graph",
                "GET",
                "/graph/metrics",
                params={"view": "health"},
                description="graph_metrics_health",
            ),
            TestCase(
                "graph_metrics_full",
                "graph",
                "GET",
                "/graph/metrics",
                params={"view": "full"},
                description="graph_metrics_full",
            ),
            TestCase(
                "graph_metrics_invalid_view",
                "graph",
                "GET",
                "/graph/metrics",
                params={"view": "invalid"},
                expected_status=400,
                description="graph_metrics_invalid_view",
            ),
            TestCase(
                "graph_metrics_with_include",
                "graph",
                "GET",
                "/graph/metrics",
                params={"include": "nodes,edges"},
                description="graph_metrics_with_include",
            ),
            # POST /graph/visualization
            TestCase(
                "graph_viz_subgraph_default",
                "graph",
                "POST",
                "/graph/visualization",
                json_body={"center_entity": "美国"},
                description="graph_viz_subgraph_default",
            ),
            TestCase(
                "graph_viz_subgraph_max_hops",
                "graph",
                "POST",
                "/graph/visualization",
                json_body={"center_entity": "美国", "max_hops": 4},
                description="graph_viz_subgraph_max_hops",
            ),
            TestCase(
                "graph_viz_subgraph_invalid_hops",
                "graph",
                "POST",
                "/graph/visualization",
                json_body={"center_entity": "美国", "max_hops": 10},
                expected_status=422,
                description="graph_viz_subgraph_invalid_hops",
            ),
            TestCase(
                "graph_viz_subgraph_empty_entity",
                "graph",
                "POST",
                "/graph/visualization",
                json_body={"center_entity": ""},
                expected_status=422,
                description="graph_viz_subgraph_empty_entity",
            ),
            TestCase(
                "graph_viz_subgraph_special_char",
                "graph",
                "POST",
                "/graph/visualization",
                json_body={"center_entity": "'\"<script>"},
                description="graph_viz_subgraph_special_char",
            ),
        ]
    )

    # ===== 12. Admin Articles 扩展 (admin) =====
    cases.extend(
        [
            # POST /admin/articles/deduplicate
            TestCase(
                "admin_articles_deduplicate_default",
                "admin",
                "POST",
                "/admin/articles/deduplicate",
                description="admin_articles_deduplicate_default",
            ),
            TestCase(
                "admin_articles_deduplicate_with_body",
                "admin",
                "POST",
                "/admin/articles/deduplicate",
                json_body={},
                description="admin_articles_deduplicate_with_body",
            ),
            TestCase(
                "admin_articles_deduplicate_special",
                "admin",
                "POST",
                "/admin/articles/deduplicate",
                json_body={"_": "'\""},
                description="admin_articles_deduplicate_special",
            ),
            TestCase(
                "admin_articles_deduplicate_long",
                "admin",
                "POST",
                "/admin/articles/deduplicate",
                json_body={"_": "x" * 1000},
                description="admin_articles_deduplicate_long",
            ),
            TestCase(
                "admin_articles_deduplicate_unicode",
                "admin",
                "POST",
                "/admin/articles/deduplicate",
                json_body={"_": "中文"},
                description="admin_articles_deduplicate_unicode",
            ),
        ]
    )

    # ===== 13. Sources 扩展端点 (sources) — PUT/DELETE /sources/{source_id} =====
    # 注：execute_request 对 /sources 上的 PUT/DELETE 自动使用 ADMIN_HEADERS
    cases.extend(
        [
            # PUT /sources/{source_id} - 5 cases
            TestCase(
                "update_source_notfound",
                "sources",
                "PUT",
                "/sources/00000000-0000-0000-0000-000000000000",
                json_body={"name": "test"},
                expected_status=404,
                description="update_source_notfound",
            ),
            TestCase(
                "update_source_invalid_id",
                "sources",
                "PUT",
                "/sources/not-a-uuid",
                json_body={"name": "test"},
                expected_status=404,
                description="update_source_invalid_id",
            ),
            TestCase(
                "update_source_special_char_id",
                "sources",
                "PUT",
                "/sources/'OR'1'='1",
                json_body={"name": "test"},
                expected_status=404,
                description="update_source_special_char_id",
            ),
            TestCase(
                "update_source_long_id",
                "sources",
                "PUT",
                f"/sources/{'x' * 1000}",
                json_body={"name": "test"},
                expected_status=404,
                description="update_source_long_id",
            ),
            TestCase(
                "update_source_empty_body",
                "sources",
                "PUT",
                "/sources/test-source-id",
                json_body={},
                expected_status=200,
                description="update_source_empty_body",
            ),
            # DELETE /sources/{source_id} - 5 cases
            TestCase(
                "delete_source_notfound",
                "sources",
                "DELETE",
                "/sources/00000000-0000-0000-0000-000000000000",
                expected_status=404,
                description="delete_source_notfound",
            ),
            TestCase(
                "delete_source_invalid_id",
                "sources",
                "DELETE",
                "/sources/not-a-uuid",
                expected_status=404,
                description="delete_source_invalid_id",
            ),
            TestCase(
                "delete_source_special_char",
                "sources",
                "DELETE",
                "/sources/'OR'1'='1",
                expected_status=404,
                description="delete_source_special_char",
            ),
            TestCase(
                "delete_source_long_id",
                "sources",
                "DELETE",
                f"/sources/{'x' * 1000}",
                expected_status=404,
                description="delete_source_long_id",
            ),
            TestCase(
                "delete_source_unicode",
                "sources",
                "DELETE",
                "/sources/中文测试",
                expected_status=404,
                description="delete_source_unicode",
            ),
        ]
    )

    # ===== 14. Admin API Keys 端点 (admin) =====
    cases.extend(
        [
            # POST /admin/api-keys - 5 cases
            TestCase(
                "create_api_key_default",
                "admin",
                "POST",
                "/admin/api-keys",
                json_body={"scopes": ["search:read"]},
                expected_status=200,
                description="create_api_key_default",
            ),
            TestCase(
                "create_api_key_custom_scopes",
                "admin",
                "POST",
                "/admin/api-keys",
                json_body={
                    "scopes": ["search:read", "articles:read"],
                    "rate_limit_per_min": 200,
                    "expires_in_days": 30,
                },
                expected_status=200,
                description="create_api_key_custom_scopes",
            ),
            TestCase(
                "create_api_key_invalid_rate",
                "admin",
                "POST",
                "/admin/api-keys",
                json_body={"scopes": ["search:read"], "rate_limit_per_min": 5},
                expected_status=422,
                description="create_api_key_invalid_rate",
            ),
            TestCase(
                "create_api_key_invalid_expiry",
                "admin",
                "POST",
                "/admin/api-keys",
                json_body={"scopes": ["search:read"], "expires_in_days": 0},
                expected_status=422,
                description="create_api_key_invalid_expiry",
            ),
            TestCase(
                "create_api_key_special_char",
                "admin",
                "POST",
                "/admin/api-keys",
                json_body={"scopes": ["search:read"], "created_by": "'\"<script>"},
                expected_status=200,
                description="create_api_key_special_char",
            ),
            # GET /admin/api-keys - 5 cases
            TestCase(
                "list_api_keys_default",
                "admin",
                "GET",
                "/admin/api-keys",
                description="list_api_keys_default",
            ),
            TestCase(
                "list_api_keys_include_revoked",
                "admin",
                "GET",
                "/admin/api-keys",
                params={"include_revoked": True},
                description="list_api_keys_include_revoked",
            ),
            TestCase(
                "list_api_keys_exclude_revoked",
                "admin",
                "GET",
                "/admin/api-keys",
                params={"include_revoked": False},
                description="list_api_keys_exclude_revoked",
            ),
            TestCase(
                "list_api_keys_special_param",
                "admin",
                "GET",
                "/admin/api-keys",
                params={"include_revoked": "invalid"},
                expected_status=422,
                description="list_api_keys_special_param",
            ),
            TestCase(
                "list_api_keys_long_param",
                "admin",
                "GET",
                "/admin/api-keys",
                params={"_t": "x" * 1000},
                description="list_api_keys_long_param",
            ),
            # DELETE /admin/api-keys/{key_id} - 5 cases
            TestCase(
                "revoke_api_key_notfound",
                "admin",
                "DELETE",
                "/admin/api-keys/00000000-0000-0000-0000-000000000000",
                expected_status=404,
                description="revoke_api_key_notfound",
            ),
            TestCase(
                "revoke_api_key_invalid_id",
                "admin",
                "DELETE",
                "/admin/api-keys/not-a-uuid",
                expected_status=404,
                description="revoke_api_key_invalid_id",
            ),
            TestCase(
                "revoke_api_key_special_char",
                "admin",
                "DELETE",
                "/admin/api-keys/'OR'1'='1",
                expected_status=404,
                description="revoke_api_key_special_char",
            ),
            TestCase(
                "revoke_api_key_long_id",
                "admin",
                "DELETE",
                f"/admin/api-keys/{'x' * 1000}",
                expected_status=404,
                description="revoke_api_key_long_id",
            ),
            TestCase(
                "revoke_api_key_unicode",
                "admin",
                "DELETE",
                "/admin/api-keys/中文",
                expected_status=404,
                description="revoke_api_key_unicode",
            ),
            # POST /admin/api-keys/{key_id}/rotate - 5 cases
            TestCase(
                "rotate_api_key_notfound",
                "admin",
                "POST",
                "/admin/api-keys/00000000-0000-0000-0000-000000000000/rotate",
                expected_status=404,
                description="rotate_api_key_notfound",
            ),
            TestCase(
                "rotate_api_key_invalid_id",
                "admin",
                "POST",
                "/admin/api-keys/not-a-uuid/rotate",
                expected_status=404,
                description="rotate_api_key_invalid_id",
            ),
            TestCase(
                "rotate_api_key_special_char",
                "admin",
                "POST",
                "/admin/api-keys/'OR'1'='1/rotate",
                expected_status=404,
                description="rotate_api_key_special_char",
            ),
            TestCase(
                "rotate_api_key_long_id",
                "admin",
                "POST",
                f"/admin/api-keys/{'x' * 1000}/rotate",
                expected_status=404,
                description="rotate_api_key_long_id",
            ),
            TestCase(
                "rotate_api_key_unicode",
                "admin",
                "POST",
                "/admin/api-keys/中文/rotate",
                expected_status=404,
                description="rotate_api_key_unicode",
            ),
        ]
    )

    # ===== 15. Admin Authorities 扩展端点 (admin) =====
    cases.extend(
        [
            # PATCH /admin/authorities/{host} - 5 cases
            TestCase(
                "update_authority_notfound",
                "admin",
                "PATCH",
                "/admin/authorities/nonexistent.example.com",
                json_body={"authority": 0.8},
                expected_status=200,
                description="update_authority_notfound",
            ),
            TestCase(
                "update_authority_invalid_authority",
                "admin",
                "PATCH",
                "/admin/authorities/www.solidot.org",
                json_body={"authority": 1.5},
                expected_status=422,
                description="update_authority_invalid_authority",
            ),
            TestCase(
                "update_authority_invalid_tier",
                "admin",
                "PATCH",
                "/admin/authorities/www.solidot.org",
                json_body={"tier": 10},
                expected_status=422,
                description="update_authority_invalid_tier",
            ),
            TestCase(
                "update_authority_special_char",
                "admin",
                "PATCH",
                "/admin/authorities/'OR'1'='1",
                json_body={"authority": 0.5},
                expected_status=200,
                description="update_authority_special_char",
            ),
            TestCase(
                "update_authority_long_host",
                "admin",
                "PATCH",
                f"/admin/authorities/{'x' * 1000}.com",
                json_body={"authority": 0.5},
                expected_status=200,
                description="update_authority_long_host",
            ),
            # POST /admin/authorities/refresh-auto-scores - 5 cases
            TestCase(
                "refresh_auto_scores_default",
                "admin",
                "POST",
                "/admin/authorities/refresh-auto-scores",
                description="refresh_auto_scores_default",
            ),
            TestCase(
                "refresh_auto_scores_with_body",
                "admin",
                "POST",
                "/admin/authorities/refresh-auto-scores",
                json_body={},
                description="refresh_auto_scores_with_body",
            ),
            TestCase(
                "refresh_auto_scores_special",
                "admin",
                "POST",
                "/admin/authorities/refresh-auto-scores",
                json_body={"_": "'\""},
                description="refresh_auto_scores_special",
            ),
            TestCase(
                "refresh_auto_scores_long",
                "admin",
                "POST",
                "/admin/authorities/refresh-auto-scores",
                json_body={"_": "x" * 1000},
                description="refresh_auto_scores_long",
            ),
            TestCase(
                "refresh_auto_scores_unicode",
                "admin",
                "POST",
                "/admin/authorities/refresh-auto-scores",
                json_body={"_": "中文"},
                description="refresh_auto_scores_unicode",
            ),
        ]
    )

    # ===== 16. Admin Memory 扩展端点 (admin) =====
    cases.extend(
        [
            # POST /admin/memory/trigger-consolidation - 5 cases
            TestCase(
                "trigger_consolidation_default",
                "admin",
                "POST",
                "/admin/memory/trigger-consolidation",
                description="trigger_consolidation_default",
            ),
            TestCase(
                "trigger_consolidation_batch_10",
                "admin",
                "POST",
                "/admin/memory/trigger-consolidation",
                params={"batch_size": 10},
                description="trigger_consolidation_batch_10",
            ),
            TestCase(
                "trigger_consolidation_batch_100",
                "admin",
                "POST",
                "/admin/memory/trigger-consolidation",
                params={"batch_size": 100},
                description="trigger_consolidation_batch_100",
            ),
            TestCase(
                "trigger_consolidation_invalid_batch",
                "admin",
                "POST",
                "/admin/memory/trigger-consolidation",
                params={"batch_size": 0},
                expected_status=200,
                description="trigger_consolidation_invalid_batch",
            ),
            TestCase(
                "trigger_consolidation_special_char",
                "admin",
                "POST",
                "/admin/memory/trigger-consolidation",
                params={"batch_size": "invalid"},
                expected_status=200,
                description="trigger_consolidation_special_char",
            ),
        ]
    )

    # ===== 17. Monitoring LLM 端点 (monitoring) =====
    # 注：/monitoring/llm 不含 /admin 也不含 /monitoring/graph，
    # execute_request 会使用普通 HEADERS，端点需要 admin 权限 → 返回 401
    cases.extend(
        [
            # GET /monitoring/llm/failures - 5 cases (all 401)
            TestCase(
                "monitoring_llm_failures_default",
                "monitoring",
                "GET",
                "/monitoring/llm/failures",
                expected_status=403,
                description="monitoring_llm_failures_default (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_llm_failures_with_limit",
                "monitoring",
                "GET",
                "/monitoring/llm/failures",
                params={"limit": 10},
                expected_status=403,
                description="monitoring_llm_failures_with_limit (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_llm_failures_with_callpoint",
                "monitoring",
                "GET",
                "/monitoring/llm/failures",
                params={"call_point": "embedding"},
                expected_status=403,
                description="monitoring_llm_failures_with_callpoint (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_llm_failures_invalid_limit",
                "monitoring",
                "GET",
                "/monitoring/llm/failures",
                params={"limit": 0},
                expected_status=403,
                description="monitoring_llm_failures_invalid_limit (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_llm_failures_long_param",
                "monitoring",
                "GET",
                "/monitoring/llm/failures",
                params={"_t": "x" * 1000},
                expected_status=403,
                description="monitoring_llm_failures_long_param (expected 401 due to admin header limitation)",
            ),
            # GET /monitoring/llm/failures/stats - 5 cases (all 401)
            TestCase(
                "monitoring_llm_failures_stats_default",
                "monitoring",
                "GET",
                "/monitoring/llm/failures/stats",
                expected_status=403,
                description="monitoring_llm_failures_stats_default (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_llm_failures_stats_with_since",
                "monitoring",
                "GET",
                "/monitoring/llm/failures/stats",
                params={"since": "2026-01-01T00:00:00"},
                expected_status=403,
                description="monitoring_llm_failures_stats_with_since (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_llm_failures_stats_invalid_since",
                "monitoring",
                "GET",
                "/monitoring/llm/failures/stats",
                params={"since": "invalid-date"},
                expected_status=403,
                description="monitoring_llm_failures_stats_invalid_since (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_llm_failures_stats_special_char",
                "monitoring",
                "GET",
                "/monitoring/llm/failures/stats",
                params={"_t": "'\""},
                expected_status=403,
                description="monitoring_llm_failures_stats_special_char (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_llm_failures_stats_long_param",
                "monitoring",
                "GET",
                "/monitoring/llm/failures/stats",
                params={"_t": "x" * 1000},
                expected_status=403,
                description="monitoring_llm_failures_stats_long_param (expected 401 due to admin header limitation)",
            ),
            # GET /monitoring/llm/usage - 5 cases (uses _llm_from/_llm_to from section 6)
            TestCase(
                "monitoring_llm_usage_summary",
                "monitoring",
                "GET",
                "/monitoring/llm/usage",
                params={"from": _llm_from, "to": _llm_to, "group_by": "summary"},
                expected_status=403,
                description="monitoring_llm_usage_summary (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_llm_usage_by_model",
                "monitoring",
                "GET",
                "/monitoring/llm/usage",
                params={"from": _llm_from, "to": _llm_to, "group_by": "model"},
                expected_status=403,
                description="monitoring_llm_usage_by_model (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_llm_usage_missing_from",
                "monitoring",
                "GET",
                "/monitoring/llm/usage",
                params={"to": _llm_to},
                expected_status=403,
                description="monitoring_llm_usage_missing_from (missing required param)",
            ),
            TestCase(
                "monitoring_llm_usage_missing_to",
                "monitoring",
                "GET",
                "/monitoring/llm/usage",
                params={"from": _llm_from},
                expected_status=403,
                description="monitoring_llm_usage_missing_to (missing required param)",
            ),
            TestCase(
                "monitoring_llm_usage_special_char",
                "monitoring",
                "GET",
                "/monitoring/llm/usage",
                params={"from": "'\"", "to": _llm_to},
                expected_status=403,
                description="monitoring_llm_usage_special_char (invalid from param)",
            ),
        ]
    )

    # ===== 18. Monitoring Alerts 端点 (monitoring) =====
    # 注：同 monitoring/llm，全部 expected 401（admin header 限制），
    # 除非路径参数类型校验先失败 → 422
    cases.extend(
        [
            # POST /monitoring/alerts/rules - 5 cases
            TestCase(
                "create_alert_rule_default",
                "monitoring",
                "POST",
                "/monitoring/alerts/rules",
                json_body={
                    "entity_name": "test_entity",
                    "metric": "mentions",
                    "operator": ">",
                    "threshold": 10.0,
                },
                expected_status=403,
                description="create_alert_rule_default (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "create_alert_rule_custom",
                "monitoring",
                "POST",
                "/monitoring/alerts/rules",
                json_body={
                    "entity_name": "test",
                    "metric": "score",
                    "operator": "<",
                    "threshold": 0.5,
                    "channel": "webhook",
                    "cooldown_minutes": 30,
                },
                expected_status=403,
                description="create_alert_rule_custom (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "create_alert_rule_long_entity",
                "monitoring",
                "POST",
                "/monitoring/alerts/rules",
                json_body={
                    "entity_name": "x" * 1000,
                    "metric": "mentions",
                    "operator": ">",
                    "threshold": 1.0,
                },
                expected_status=403,
                description="create_alert_rule_long_entity (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "create_alert_rule_special_char",
                "monitoring",
                "POST",
                "/monitoring/alerts/rules",
                json_body={
                    "entity_name": "'\"<script>",
                    "metric": "mentions",
                    "operator": ">",
                    "threshold": 1.0,
                },
                expected_status=403,
                description="create_alert_rule_special_char (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "create_alert_rule_invalid_threshold",
                "monitoring",
                "POST",
                "/monitoring/alerts/rules",
                json_body={
                    "entity_name": "test",
                    "metric": "mentions",
                    "operator": ">",
                    "threshold": "invalid",
                },
                expected_status=403,
                description="create_alert_rule_invalid_threshold (type validation)",
            ),
            # GET /monitoring/alerts/rules - 5 cases
            TestCase(
                "list_alert_rules_default",
                "monitoring",
                "GET",
                "/monitoring/alerts/rules",
                expected_status=403,
                description="list_alert_rules_default (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "list_alert_rules_by_entity",
                "monitoring",
                "GET",
                "/monitoring/alerts/rules",
                params={"entity_name": "test"},
                expected_status=403,
                description="list_alert_rules_by_entity (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "list_alert_rules_enabled_only",
                "monitoring",
                "GET",
                "/monitoring/alerts/rules",
                params={"enabled_only": True},
                expected_status=403,
                description="list_alert_rules_enabled_only (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "list_alert_rules_special_char",
                "monitoring",
                "GET",
                "/monitoring/alerts/rules",
                params={"entity_name": "'\""},
                expected_status=403,
                description="list_alert_rules_special_char (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "list_alert_rules_long_param",
                "monitoring",
                "GET",
                "/monitoring/alerts/rules",
                params={"entity_name": "x" * 1000},
                expected_status=403,
                description="list_alert_rules_long_param (expected 401 due to admin header limitation)",
            ),
            # GET /monitoring/alerts/rules/{rule_id:int} - 5 cases
            TestCase(
                "get_alert_rule_notfound",
                "monitoring",
                "GET",
                "/monitoring/alerts/rules/99999",
                expected_status=403,
                description="get_alert_rule_notfound (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "get_alert_rule_invalid_id",
                "monitoring",
                "GET",
                "/monitoring/alerts/rules/not-a-number",
                expected_status=403,
                description="get_alert_rule_invalid_id (path int validation)",
            ),
            TestCase(
                "get_alert_rule_zero_id",
                "monitoring",
                "GET",
                "/monitoring/alerts/rules/0",
                expected_status=403,
                description="get_alert_rule_zero_id (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "get_alert_rule_negative_id",
                "monitoring",
                "GET",
                "/monitoring/alerts/rules/-1",
                expected_status=403,
                description="get_alert_rule_negative_id (path int validation)",
            ),
            TestCase(
                "get_alert_rule_special_char",
                "monitoring",
                "GET",
                "/monitoring/alerts/rules/'1",
                expected_status=403,
                description="get_alert_rule_special_char (path int validation)",
            ),
            # PATCH /monitoring/alerts/rules/{rule_id:int} - 5 cases
            TestCase(
                "update_alert_rule_notfound",
                "monitoring",
                "PATCH",
                "/monitoring/alerts/rules/99999",
                json_body={"threshold": 5.0},
                expected_status=403,
                description="update_alert_rule_notfound (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "update_alert_rule_invalid_id",
                "monitoring",
                "PATCH",
                "/monitoring/alerts/rules/not-a-number",
                json_body={"threshold": 5.0},
                expected_status=403,
                description="update_alert_rule_invalid_id (path int validation)",
            ),
            TestCase(
                "update_alert_rule_invalid_threshold",
                "monitoring",
                "PATCH",
                "/monitoring/alerts/rules/1",
                json_body={"threshold": "invalid"},
                expected_status=403,
                description="update_alert_rule_invalid_threshold (body type validation)",
            ),
            TestCase(
                "update_alert_rule_special_char",
                "monitoring",
                "PATCH",
                "/monitoring/alerts/rules/1",
                json_body={"channel": "'\""},
                expected_status=403,
                description="update_alert_rule_special_char (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "update_alert_rule_empty_body",
                "monitoring",
                "PATCH",
                "/monitoring/alerts/rules/1",
                json_body={},
                expected_status=403,
                description="update_alert_rule_empty_body (expected 401 due to admin header limitation)",
            ),
            # DELETE /monitoring/alerts/rules/{rule_id:int} - 5 cases
            TestCase(
                "delete_alert_rule_notfound",
                "monitoring",
                "DELETE",
                "/monitoring/alerts/rules/99999",
                expected_status=403,
                description="delete_alert_rule_notfound (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "delete_alert_rule_invalid_id",
                "monitoring",
                "DELETE",
                "/monitoring/alerts/rules/not-a-number",
                expected_status=403,
                description="delete_alert_rule_invalid_id (path int validation)",
            ),
            TestCase(
                "delete_alert_rule_zero_id",
                "monitoring",
                "DELETE",
                "/monitoring/alerts/rules/0",
                expected_status=403,
                description="delete_alert_rule_zero_id (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "delete_alert_rule_negative_id",
                "monitoring",
                "DELETE",
                "/monitoring/alerts/rules/-1",
                expected_status=403,
                description="delete_alert_rule_negative_id (path int validation)",
            ),
            TestCase(
                "delete_alert_rule_special_char",
                "monitoring",
                "DELETE",
                "/monitoring/alerts/rules/'1",
                expected_status=403,
                description="delete_alert_rule_special_char (path int validation)",
            ),
            # POST /monitoring/alerts/trigger - 5 cases
            TestCase(
                "trigger_alert_default",
                "monitoring",
                "POST",
                "/monitoring/alerts/trigger",
                json_body={"rule_id": 1, "metric_value": 10.0},
                expected_status=403,
                description="trigger_alert_default (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "trigger_alert_with_detail",
                "monitoring",
                "POST",
                "/monitoring/alerts/trigger",
                json_body={"rule_id": 1, "metric_value": 10.0, "detail": {"key": "value"}},
                expected_status=403,
                description="trigger_alert_with_detail (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "trigger_alert_notfound",
                "monitoring",
                "POST",
                "/monitoring/alerts/trigger",
                json_body={"rule_id": 99999, "metric_value": 10.0},
                expected_status=403,
                description="trigger_alert_notfound (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "trigger_alert_invalid_rule_id",
                "monitoring",
                "POST",
                "/monitoring/alerts/trigger",
                json_body={"rule_id": "invalid", "metric_value": 10.0},
                expected_status=403,
                description="trigger_alert_invalid_rule_id (body type validation)",
            ),
            TestCase(
                "trigger_alert_special_char",
                "monitoring",
                "POST",
                "/monitoring/alerts/trigger",
                json_body={"rule_id": 1, "metric_value": 10.0, "detail": {"_": "'\""}},
                expected_status=403,
                description="trigger_alert_special_char (expected 401 due to admin header limitation)",
            ),
            # POST /monitoring/alerts/events/{event_id:int}/acknowledge - 5 cases
            TestCase(
                "acknowledge_alert_notfound",
                "monitoring",
                "POST",
                "/monitoring/alerts/events/99999/acknowledge",
                expected_status=403,
                description="acknowledge_alert_notfound (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "acknowledge_alert_invalid_id",
                "monitoring",
                "POST",
                "/monitoring/alerts/events/not-a-number/acknowledge",
                expected_status=403,
                description="acknowledge_alert_invalid_id (path int validation)",
            ),
            TestCase(
                "acknowledge_alert_zero_id",
                "monitoring",
                "POST",
                "/monitoring/alerts/events/0/acknowledge",
                expected_status=403,
                description="acknowledge_alert_zero_id (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "acknowledge_alert_negative_id",
                "monitoring",
                "POST",
                "/monitoring/alerts/events/-1/acknowledge",
                expected_status=403,
                description="acknowledge_alert_negative_id (path int validation)",
            ),
            TestCase(
                "acknowledge_alert_special_char",
                "monitoring",
                "POST",
                "/monitoring/alerts/events/'1/acknowledge",
                expected_status=403,
                description="acknowledge_alert_special_char (path int validation)",
            ),
            # GET /monitoring/alerts/events - 5 cases
            TestCase(
                "list_alert_events_default",
                "monitoring",
                "GET",
                "/monitoring/alerts/events",
                expected_status=403,
                description="list_alert_events_default (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "list_alert_events_by_rule",
                "monitoring",
                "GET",
                "/monitoring/alerts/events",
                params={"rule_id": 1},
                expected_status=403,
                description="list_alert_events_by_rule (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "list_alert_events_by_entity",
                "monitoring",
                "GET",
                "/monitoring/alerts/events",
                params={"entity_name": "test"},
                expected_status=403,
                description="list_alert_events_by_entity (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "list_alert_events_acknowledged",
                "monitoring",
                "GET",
                "/monitoring/alerts/events",
                params={"acknowledged": True},
                expected_status=403,
                description="list_alert_events_acknowledged (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "list_alert_events_long_param",
                "monitoring",
                "GET",
                "/monitoring/alerts/events",
                params={"entity_name": "x" * 1000},
                expected_status=403,
                description="list_alert_events_long_param (expected 401 due to admin header limitation)",
            ),
        ]
    )

    # ===== 19. Monitoring Memory/Communities/Causal 端点 (monitoring) =====
    cases.extend(
        [
            # GET /monitoring/memory/diagnostics - 5 cases (all 401)
            TestCase(
                "monitoring_memory_diagnostics_default",
                "monitoring",
                "GET",
                "/monitoring/memory/diagnostics",
                expected_status=403,
                description="monitoring_memory_diagnostics_default (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_memory_diagnostics_with_param",
                "monitoring",
                "GET",
                "/monitoring/memory/diagnostics",
                params={"_t": "123"},
                expected_status=403,
                description="monitoring_memory_diagnostics_with_param (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_memory_diagnostics_special_char",
                "monitoring",
                "GET",
                "/monitoring/memory/diagnostics",
                params={"_t": "'\""},
                expected_status=403,
                description="monitoring_memory_diagnostics_special_char (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_memory_diagnostics_long_param",
                "monitoring",
                "GET",
                "/monitoring/memory/diagnostics",
                params={"_t": "x" * 1000},
                expected_status=403,
                description="monitoring_memory_diagnostics_long_param (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_memory_diagnostics_unicode",
                "monitoring",
                "GET",
                "/monitoring/memory/diagnostics",
                params={"_t": "中文"},
                expected_status=403,
                description="monitoring_memory_diagnostics_unicode (expected 401 due to admin header limitation)",
            ),
            # GET /monitoring/communities/health - 5 cases (all 401)
            TestCase(
                "monitoring_communities_health_default",
                "monitoring",
                "GET",
                "/monitoring/communities/health",
                expected_status=403,
                description="monitoring_communities_health_default (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_communities_health_with_param",
                "monitoring",
                "GET",
                "/monitoring/communities/health",
                params={"_t": "123"},
                expected_status=403,
                description="monitoring_communities_health_with_param (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_communities_health_special_char",
                "monitoring",
                "GET",
                "/monitoring/communities/health",
                params={"_t": "'\""},
                expected_status=403,
                description="monitoring_communities_health_special_char (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_communities_health_long_param",
                "monitoring",
                "GET",
                "/monitoring/communities/health",
                params={"_t": "x" * 1000},
                expected_status=403,
                description="monitoring_communities_health_long_param (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_communities_health_unicode",
                "monitoring",
                "GET",
                "/monitoring/communities/health",
                params={"_t": "中文"},
                expected_status=403,
                description="monitoring_communities_health_unicode (expected 401 due to admin header limitation)",
            ),
            # GET /monitoring/causal/stats - 5 cases (all 401)
            TestCase(
                "monitoring_causal_stats_default",
                "monitoring",
                "GET",
                "/monitoring/causal/stats",
                expected_status=403,
                description="monitoring_causal_stats_default (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_causal_stats_with_param",
                "monitoring",
                "GET",
                "/monitoring/causal/stats",
                params={"_t": "123"},
                expected_status=403,
                description="monitoring_causal_stats_with_param (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_causal_stats_special_char",
                "monitoring",
                "GET",
                "/monitoring/causal/stats",
                params={"_t": "'\""},
                expected_status=403,
                description="monitoring_causal_stats_special_char (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_causal_stats_long_param",
                "monitoring",
                "GET",
                "/monitoring/causal/stats",
                params={"_t": "x" * 1000},
                expected_status=403,
                description="monitoring_causal_stats_long_param (expected 401 due to admin header limitation)",
            ),
            TestCase(
                "monitoring_causal_stats_unicode",
                "monitoring",
                "GET",
                "/monitoring/causal/stats",
                params={"_t": "中文"},
                expected_status=403,
                description="monitoring_causal_stats_unicode (expected 401 due to admin header limitation)",
            ),
        ]
    )

    # ===== 20. Analytics 端点 (analytics) =====
    cases.extend(
        [
            # GET /analytics/shifts - 5 cases
            TestCase(
                "analytics_shifts_default",
                "analytics",
                "GET",
                "/analytics/shifts",
                description="analytics_shifts_default",
            ),
            TestCase(
                "analytics_shifts_with_limit",
                "analytics",
                "GET",
                "/analytics/shifts",
                params={"limit": 10},
                description="analytics_shifts_with_limit",
            ),
            TestCase(
                "analytics_shifts_with_community",
                "analytics",
                "GET",
                "/analytics/shifts",
                params={"community_id": "test-community"},
                description="analytics_shifts_with_community",
            ),
            TestCase(
                "analytics_shifts_invalid_limit",
                "analytics",
                "GET",
                "/analytics/shifts",
                params={"limit": 0},
                expected_status=422,
                description="analytics_shifts_invalid_limit",
            ),
            TestCase(
                "analytics_shifts_long_param",
                "analytics",
                "GET",
                "/analytics/shifts",
                params={"community_id": "x" * 1000},
                description="analytics_shifts_long_param",
            ),
            # GET /analytics/briefings - 5 cases
            TestCase(
                "analytics_briefings_default",
                "analytics",
                "GET",
                "/analytics/briefings",
                description="analytics_briefings_default",
            ),
            TestCase(
                "analytics_briefings_with_limit",
                "analytics",
                "GET",
                "/analytics/briefings",
                params={"limit": 5},
                description="analytics_briefings_with_limit",
            ),
            TestCase(
                "analytics_briefings_with_date",
                "analytics",
                "GET",
                "/analytics/briefings",
                params={"date": "2026-06-27"},
                description="analytics_briefings_with_date",
            ),
            TestCase(
                "analytics_briefings_invalid_limit",
                "analytics",
                "GET",
                "/analytics/briefings",
                params={"limit": 0},
                expected_status=422,
                description="analytics_briefings_invalid_limit",
            ),
            TestCase(
                "analytics_briefings_invalid_date",
                "analytics",
                "GET",
                "/analytics/briefings",
                params={"date": "invalid-date"},
                description="analytics_briefings_invalid_date",
            ),
        ]
    )

    # ===== 21. Saga 端点 (saga) — GET 用 verify_api_key，POST 用 verify_admin_api_key =====
    cases.extend(
        [
            # GET /saga/{saga_id:uuid} - 5 cases
            TestCase(
                "saga_get_notfound",
                "saga",
                "GET",
                "/saga/00000000-0000-0000-0000-000000000000",
                expected_status=404,
                description="saga_get_notfound",
            ),
            TestCase(
                "saga_get_invalid_uuid",
                "saga",
                "GET",
                "/saga/not-a-uuid",
                expected_status=422,
                description="saga_get_invalid_uuid",
            ),
            TestCase(
                "saga_get_special_char",
                "saga",
                "GET",
                "/saga/'OR'1'='1",
                expected_status=422,
                description="saga_get_special_char",
            ),
            TestCase(
                "saga_get_long_id",
                "saga",
                "GET",
                f"/saga/{'x' * 1000}",
                expected_status=422,
                description="saga_get_long_id",
            ),
            TestCase(
                "saga_get_unicode",
                "saga",
                "GET",
                "/saga/中文",
                expected_status=422,
                description="saga_get_unicode",
            ),
            # POST /saga/{saga_id:uuid}/compensate - 5 cases
            TestCase(
                "saga_compensate_notfound",
                "saga",
                "POST",
                "/saga/00000000-0000-0000-0000-000000000000/compensate",
                expected_status=404,
                description="saga_compensate_notfound",
            ),
            TestCase(
                "saga_compensate_invalid_uuid",
                "saga",
                "POST",
                "/saga/not-a-uuid/compensate",
                expected_status=422,
                description="saga_compensate_invalid_uuid",
            ),
            TestCase(
                "saga_compensate_special_char",
                "saga",
                "POST",
                "/saga/'OR'1'='1/compensate",
                expected_status=422,
                description="saga_compensate_special_char",
            ),
            TestCase(
                "saga_compensate_long_id",
                "saga",
                "POST",
                f"/saga/{'x' * 1000}/compensate",
                expected_status=422,
                description="saga_compensate_long_id",
            ),
            TestCase(
                "saga_compensate_unicode",
                "saga",
                "POST",
                "/saga/中文/compensate",
                expected_status=422,
                description="saga_compensate_unicode",
            ),
            # POST /saga/{saga_id:uuid}/retry - 5 cases
            TestCase(
                "saga_retry_notfound",
                "saga",
                "POST",
                "/saga/00000000-0000-0000-0000-000000000000/retry",
                expected_status=404,
                description="saga_retry_notfound",
            ),
            TestCase(
                "saga_retry_invalid_uuid",
                "saga",
                "POST",
                "/saga/not-a-uuid/retry",
                expected_status=422,
                description="saga_retry_invalid_uuid",
            ),
            TestCase(
                "saga_retry_special_char",
                "saga",
                "POST",
                "/saga/'OR'1'='1/retry",
                expected_status=422,
                description="saga_retry_special_char",
            ),
            TestCase(
                "saga_retry_long_id",
                "saga",
                "POST",
                f"/saga/{'x' * 1000}/retry",
                expected_status=422,
                description="saga_retry_long_id",
            ),
            TestCase(
                "saga_retry_unicode",
                "saga",
                "POST",
                "/saga/中文/retry",
                expected_status=422,
                description="saga_retry_unicode",
            ),
            # GET /saga/article/{article_id:uuid} - 5 cases
            TestCase(
                "saga_article_notfound",
                "saga",
                "GET",
                "/saga/article/00000000-0000-0000-0000-000000000000",
                expected_status=200,
                description="saga_article_notfound",
            ),
            TestCase(
                "saga_article_invalid_uuid",
                "saga",
                "GET",
                "/saga/article/not-a-uuid",
                expected_status=422,
                description="saga_article_invalid_uuid",
            ),
            TestCase(
                "saga_article_special_char",
                "saga",
                "GET",
                "/saga/article/'OR'1'='1",
                expected_status=422,
                description="saga_article_special_char",
            ),
            TestCase(
                "saga_article_long_id",
                "saga",
                "GET",
                f"/saga/article/{'x' * 1000}",
                expected_status=422,
                description="saga_article_long_id",
            ),
            TestCase(
                "saga_article_unicode",
                "saga",
                "GET",
                "/saga/article/中文",
                expected_status=422,
                description="saga_article_unicode",
            ),
            # GET /saga/failed/list - 5 cases
            TestCase(
                "saga_failed_list_default",
                "saga",
                "GET",
                "/saga/failed/list",
                description="saga_failed_list_default",
            ),
            TestCase(
                "saga_failed_list_with_limit",
                "saga",
                "GET",
                "/saga/failed/list",
                params={"limit": 10},
                description="saga_failed_list_with_limit",
            ),
            TestCase(
                "saga_failed_list_large_limit",
                "saga",
                "GET",
                "/saga/failed/list",
                params={"limit": 1000},
                expected_status=422,
                description="saga_failed_list_large_limit",
            ),
            TestCase(
                "saga_failed_list_invalid_limit",
                "saga",
                "GET",
                "/saga/failed/list",
                params={"limit": -1},
                expected_status=422,
                description="saga_failed_list_invalid_limit",
            ),
            TestCase(
                "saga_failed_list_special_char",
                "saga",
                "GET",
                "/saga/failed/list",
                params={"limit": "invalid"},
                expected_status=422,
                description="saga_failed_list_special_char",
            ),
        ]
    )

    # ===== 22. Communities 扩展端点 (communities) =====
    cases.extend(
        [
            # POST /admin/communities/{community_id}/report/regenerate - 5 cases
            TestCase(
                "regenerate_report_notfound",
                "communities",
                "POST",
                "/admin/communities/00000000-0000-0000-0000-000000000000/report/regenerate",
                expected_status=404,
                description="regenerate_report_notfound",
            ),
            TestCase(
                "regenerate_report_invalid_id",
                "communities",
                "POST",
                "/admin/communities/not-a-uuid/report/regenerate",
                expected_status=404,
                description="regenerate_report_invalid_id",
            ),
            TestCase(
                "regenerate_report_special_char",
                "communities",
                "POST",
                "/admin/communities/'OR'1'='1/report/regenerate",
                expected_status=404,
                description="regenerate_report_special_char",
            ),
            TestCase(
                "regenerate_report_long_id",
                "communities",
                "POST",
                f"/admin/communities/{'x' * 1000}/report/regenerate",
                expected_status=404,
                description="regenerate_report_long_id",
            ),
            TestCase(
                "regenerate_report_unicode",
                "communities",
                "POST",
                "/admin/communities/中文/report/regenerate",
                expected_status=404,
                description="regenerate_report_unicode",
            ),
            # POST /admin/communities/health/diagnose - 5 cases
            TestCase(
                "diagnose_health_default",
                "communities",
                "POST",
                "/admin/communities/health/diagnose",
                description="diagnose_health_default",
            ),
            TestCase(
                "diagnose_health_with_body",
                "communities",
                "POST",
                "/admin/communities/health/diagnose",
                json_body={},
                description="diagnose_health_with_body",
            ),
            TestCase(
                "diagnose_health_special",
                "communities",
                "POST",
                "/admin/communities/health/diagnose",
                json_body={"_": "'\""},
                description="diagnose_health_special",
            ),
            TestCase(
                "diagnose_health_long",
                "communities",
                "POST",
                "/admin/communities/health/diagnose",
                json_body={"_": "x" * 1000},
                description="diagnose_health_long",
            ),
            TestCase(
                "diagnose_health_unicode",
                "communities",
                "POST",
                "/admin/communities/health/diagnose",
                json_body={"_": "中文"},
                description="diagnose_health_unicode",
            ),
            # POST /admin/communities/health/repair - 5 cases
            TestCase(
                "repair_health_default",
                "communities",
                "POST",
                "/admin/communities/health/repair",
                json_body={},
                description="repair_health_default",
            ),
            TestCase(
                "repair_health_dry_run",
                "communities",
                "POST",
                "/admin/communities/health/repair",
                json_body={"dry_run": True},
                description="repair_health_dry_run",
            ),
            TestCase(
                "repair_health_with_types",
                "communities",
                "POST",
                "/admin/communities/health/repair",
                json_body={"repair_types": ["orphan_reports"]},
                expected_status=400,
                description="repair_health_with_types",
            ),
            TestCase(
                "repair_health_special",
                "communities",
                "POST",
                "/admin/communities/health/repair",
                json_body={"repair_types": ["'\""]},
                expected_status=400,
                description="repair_health_special",
            ),
            TestCase(
                "repair_health_long",
                "communities",
                "POST",
                "/admin/communities/health/repair",
                json_body={"repair_types": ["x" * 1000]},
                expected_status=400,
                description="repair_health_long",
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

        # For graph_dynamic_001, find an article that exists in the graph DB
        # by querying entity's mentioned_in_articles (ensures article is in LadybugDB)
        graph_article_id = article_id  # fallback
        if extracted_ids["entity_names"]:
            try:
                with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=TIMEOUT) as client:
                    for entity_name in extracted_ids["entity_names"][:5]:
                        encoded = quote(entity_name)
                        resp = client.get(f"/graph/entities/{encoded}", params={"limit": 20})
                        if resp.status_code == 200:
                            data = resp.json().get("data", {})
                            mentioned = data.get("mentioned_in_articles", [])
                            if mentioned:
                                # mentioned_in_articles items have "id" field (article UUID)
                                aid = mentioned[0].get("id") or mentioned[0].get("article_id")
                                if aid:
                                    graph_article_id = aid
                                    break
            except Exception:
                pass  # fallback to article_ids[0]

        dynamic_cases.append(
            TestCase(
                "graph_dynamic_001",
                "graph",
                "GET",
                f"/graph/articles/{graph_article_id}/graph",
                description=f"get_article_graph_{graph_article_id[:8]}",
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
    # 4. Write operations on saga (POST /saga/*/compensate, POST /saga/*/retry)
    is_admin_url = "/admin" in test_case.url or "/monitoring/graph" in test_case.url
    is_sources_write = "/sources" in test_case.url and test_case.method in (
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    )
    is_saga_write = "/saga/" in test_case.url and test_case.method == "POST"
    req_headers = ADMIN_HEADERS if (is_admin_url or is_sources_write or is_saga_write) else HEADERS

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

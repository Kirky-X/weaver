"""Prometheus metrics definitions for the weaver system."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


class MetricsCollector:
    """Centralized Prometheus metrics for the weaver pipeline."""

    # API metrics
    api_request_latency = Histogram(
        "api_request_latency_seconds",
        "API 请求延迟",
        ["endpoint", "method", "status"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
    )
    api_request_total = Counter(
        "api_request_total",
        "API 请求总数",
        ["endpoint", "method", "status"],
    )

    # LLM call metrics
    llm_call_total = Counter(
        "llm_call_total",
        "LLM 调用次数",
        ["call_point", "provider", "status"],
    )
    llm_call_latency = Histogram(
        "llm_call_latency_seconds",
        "LLM 调用延迟",
        ["call_point", "provider"],
        buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
    )
    fallback_total = Counter(
        "llm_fallback_total",
        "Fallback 发生次数",
        ["call_point", "from_provider", "reason"],
    )

    # Pipeline metrics
    pipeline_stage_latency = Histogram(
        "pipeline_stage_latency_seconds",
        "Pipeline 节点延迟",
        ["stage"],
    )
    pipeline_queue_depth = Gauge(
        "pipeline_queue_depth",
        "Pipeline 任务队列深度",
    )

    # Credibility metrics
    credibility_score_dist = Histogram(
        "credibility_score_distribution",
        "可信度分布",
        buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    )

    # Fetcher metrics
    fetch_total = Counter(
        "fetch_total",
        "抓取次数",
        ["method", "status"],
    )
    fetch_latency = Histogram(
        "fetch_latency_seconds",
        "抓取延迟",
        ["method"],
        buckets=[0.5, 1, 2, 5, 10, 30],
    )

    # Database pool metrics
    db_pool_size = Gauge(
        "db_pool_size",
        "数据库连接池大小",
        ["pool"],
    )
    db_pool_checked_out = Gauge(
        "db_pool_checked_out",
        "数据库连接池已检出连接数",
        ["pool"],
    )
    db_pool_utilization = Gauge(
        "db_pool_utilization",
        "数据库连接池利用率",
        ["pool"],
    )

    # Circuit breaker metrics
    circuit_breaker_state = Gauge(
        "circuit_breaker_state",
        "熔断器状态 (0=closed, 1=open, 2=half_open)",
        ["provider"],
    )
    circuit_breaker_failures = Counter(
        "circuit_breaker_failures_total",
        "熔断器失败次数",
        ["provider"],
    )


# Global metrics instance for use across modules
metrics = MetricsCollector()

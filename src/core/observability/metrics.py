# Copyright (c) 2026 KirkyX. All Rights Reserved
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

    # LLM token metrics
    llm_token_input_total = Counter(
        "llm_token_input_total",
        "Total number of input tokens used in LLM calls",
        ["provider", "model", "call_point"],
    )
    llm_token_output_total = Counter(
        "llm_token_output_total",
        "Total number of output tokens used in LLM calls",
        ["provider", "model", "call_point"],
    )
    llm_token_total = Counter(
        "llm_token_total",
        "Total number of tokens used in LLM calls",
        ["provider", "model", "call_point"],
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

    # Health check metrics
    health_check_status = Gauge(
        "health_check_status",
        "健康检查状态 (1=ok, 0=error, -1=timeout, -2=unavailable)",
        ["service"],
    )
    health_check_latency = Histogram(
        "health_check_latency_seconds",
        "健康检查延迟",
        ["service"],
        buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1],
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

    # Deduplication metrics
    dedup_total = Counter(
        "weaver_dedup_total",
        "各阶段去重过滤的文章数",
        ["stage"],  # stage: url, title, vector
    )
    dedup_ratio = Gauge(
        "weaver_dedup_ratio",
        "各阶段去重率",
        ["stage"],
    )
    dedup_processing_time = Histogram(
        "weaver_dedup_processing_time_seconds",
        "各阶段去重处理时间",
        ["stage"],
        buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1],
    )
    articles_processed_total = Counter(
        "weaver_articles_processed_total",
        "处理的文章总数",
    )
    articles_deduped_total = Counter(
        "weaver_articles_deduped_total",
        "被去重的文章总数",
    )

    # Persistence status gauge (updated by scheduled job)
    persist_status_count = Gauge(
        "persist_status_count",
        "各持久化状态的文章数量",
        ["status"],
    )

    # Pipeline retry metrics
    pipeline_retry_total = Counter(
        "pipeline_retry_total",
        "Pipeline 重试总数",
        ["status"],  # status: started, completed
    )
    pipeline_retry_success_total = Counter(
        "pipeline_retry_success_total",
        "Pipeline 重试成功数量",
        ["type"],  # type: pending, stuck, failed
    )

    # Scheduler job metrics
    scheduler_job_duration = Histogram(
        "scheduler_job_duration_seconds",
        "Scheduled job execution duration",
        ["job", "status"],
        buckets=[0.5, 1, 5, 10, 30, 60, 120, 300, 600],
    )
    scheduler_job_total = Counter(
        "scheduler_job_total",
        "Total scheduled job executions",
        ["job", "status"],
    )


# Global metrics instance for use across modules
metrics = MetricsCollector()

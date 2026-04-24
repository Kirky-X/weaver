# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for pipeline and LLM metrics in MetricsCollector."""

from core.observability.metrics import MetricsCollector


class TestPipelineArticleLatency:
    """Test pipeline_article_latency histogram."""

    def test_histogram_exists(self):
        assert hasattr(MetricsCollector, "pipeline_article_latency")

    def test_observe_with_category(self):
        MetricsCollector.pipeline_article_latency.labels(category="politics").observe(5.0)
        MetricsCollector.pipeline_article_latency.labels(category="technology").observe(10.0)

    def test_observe_with_unknown_category(self):
        MetricsCollector.pipeline_article_latency.labels(category="unknown").observe(1.0)


class TestPipelineFailureCount:
    """Test pipeline_failure_count counter."""

    def test_counter_exists(self):
        assert hasattr(MetricsCollector, "pipeline_failure_count")

    def test_inc_with_stage_and_error_type(self):
        MetricsCollector.pipeline_failure_count.labels(
            stage="phase1", error_type="ValueError"
        ).inc()
        MetricsCollector.pipeline_failure_count.labels(
            stage="phase3", error_type="TimeoutError"
        ).inc()

    def test_inc_persist_failure(self):
        MetricsCollector.pipeline_failure_count.labels(
            stage="persist_pg", error_type="ConnectionError"
        ).inc()
        MetricsCollector.pipeline_failure_count.labels(
            stage="persist_neo4j", error_type="ServiceUnavailable"
        ).inc()


class TestExistingMetricsPreserved:
    """Verify existing metrics are not broken by new additions."""

    def test_pipeline_stage_latency_exists(self):
        assert hasattr(MetricsCollector, "pipeline_stage_latency")

    def test_llm_call_total_exists(self):
        assert hasattr(MetricsCollector, "llm_call_total")

    def test_llm_token_total_exists(self):
        assert hasattr(MetricsCollector, "llm_token_total")

    def test_pipeline_retry_total_exists(self):
        assert hasattr(MetricsCollector, "pipeline_retry_total")

    def test_pipeline_queue_depth_exists(self):
        assert hasattr(MetricsCollector, "pipeline_queue_depth")

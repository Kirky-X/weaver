# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Analytics module - LLM usage statistics and metrics.

Consolidates LLM usage tracking and metrics:
- LLM usage repository (hourly aggregation, multi-dimensional queries)
- LLM failure tracking
- Prometheus metrics
- Fake news detection
"""

from modules.analytics.fake_news_detector import (
    FakeNewsDetector,
    FakeNewsDetectorConfig,
    FakeNewsLevel,
)
from modules.analytics.llm_failure.repo import LLMFailureRepo
from modules.analytics.llm_usage.aggregator import (
    aggregate_usage_data,
    flush_usage_buffer,
)
from modules.analytics.llm_usage.buffer import LLMUsageBuffer
from modules.analytics.llm_usage.repo import LLMUsageRepo
from modules.analytics.sentiment_analyzer import (
    SentimentAnalyzer,
    SentimentAnalyzerConfig,
)

__all__ = [
    "FakeNewsDetector",
    "FakeNewsDetectorConfig",
    "FakeNewsLevel",
    "LLMFailureRepo",
    "LLMUsageBuffer",
    "LLMUsageRepo",
    "SentimentAnalyzer",
    "SentimentAnalyzerConfig",
    "aggregate_usage_data",
    "flush_usage_buffer",
]

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Analytics module - LLM usage statistics and metrics.

Consolidates LLM usage tracking and metrics:
- LLM usage repository (hourly aggregation, multi-dimensional queries)
- LLM failure tracking
- Prometheus metrics
- Fake news detection
"""

from modules.analytics.alert_service import AlertService
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
from modules.analytics.shift_detector import SentimentShiftDetector, ShiftConfig
from modules.analytics.storage import AnalyticsStorage

__all__ = [
    "AlertService",
    "AnalyticsStorage",
    "FakeNewsDetector",
    "FakeNewsDetectorConfig",
    "FakeNewsLevel",
    "LLMFailureRepo",
    "LLMUsageBuffer",
    "LLMUsageRepo",
    "SentimentAnalyzer",
    "SentimentAnalyzerConfig",
    "SentimentShiftDetector",
    "ShiftConfig",
    "aggregate_usage_data",
    "flush_usage_buffer",
]

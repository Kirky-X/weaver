# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Analytics module - LLM usage statistics and metrics.

Consolidates LLM usage tracking and metrics:
- LLM usage repository (hourly aggregation, multi-dimensional queries)
- LLM failure tracking
- Prometheus metrics
"""

from modules.analytics.llm_failure.repo import LLMFailureRepo
from modules.analytics.llm_usage.aggregator import (
    aggregate_usage_data,
    flush_usage_buffer,
)
from modules.analytics.llm_usage.buffer import LLMUsageBuffer
from modules.analytics.llm_usage.repo import LLMUsageRepo

__all__ = [
    "LLMFailureRepo",
    "LLMUsageBuffer",
    "LLMUsageRepo",
    "aggregate_usage_data",
    "flush_usage_buffer",
]

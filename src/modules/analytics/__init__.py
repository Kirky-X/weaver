# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Analytics module - LLM usage statistics and metrics.

Consolidates LLM usage tracking and metrics:
- LLM usage repository (hourly aggregation, multi-dimensional queries)
- LLM failure tracking
- Prometheus metrics
"""

from modules.analytics.llm_failure_cleanup import LLMFailureCleanupThread
from modules.analytics.llm_failure_repo import LLMFailureRepo
from modules.analytics.llm_usage_aggregator import (
    LLMUsageAggregatorThread,
    LLMUsageRawCleanupThread,
)
from modules.analytics.llm_usage_buffer import LLMUsageBuffer
from modules.analytics.llm_usage_repo import LLMUsageRepo

__all__ = [
    # LLM usage
    "LLMUsageRepo",
    "LLMUsageBuffer",
    "LLMUsageAggregatorThread",
    "LLMUsageRawCleanupThread",
    # LLM failure
    "LLMFailureRepo",
    "LLMFailureCleanupThread",
]

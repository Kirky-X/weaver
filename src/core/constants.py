# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Centralized string constants and enums for the weaver application.

This module provides type-safe constants for:
- Redis key prefixes and patterns
- Pipeline stage names
- Configuration keys
- Status values

Using enums instead of raw strings improves:
- Type safety (compile-time checking)
- IDE support (autocomplete, refactoring)
- Searchability (find all usages of a constant)
"""

from __future__ import annotations

import enum

# ── Redis Key Constants ────────────────────────────────────────


class RedisKeys:
    """Redis key patterns and prefixes.

    All Redis keys should use constants from this class
    to ensure consistency and easy key management.
    """

    # Crawl queue keys
    CRAWL_QUEUE = "crawl:queue"
    CRAWL_RETRY_PREFIX = "crawl:retry:"
    CRAWL_DEAD_LETTER = "crawl:dead"

    # Pipeline keys
    PIPELINE_TASK_QUEUE = "pipeline:task_queue"
    PIPELINE_TASK_STATUS = "pipeline:task_status"

    # Embedding cache
    EMBEDDING_PREFIX = "emb:"

    @classmethod
    def crawl_retry(cls, host: str) -> str:
        """Generate retry queue key for a specific host."""
        return f"{cls.CRAWL_RETRY_PREFIX}{host}"


# ── Pipeline Stage Constants ───────────────────────────────────


class PipelineStage(str, enum.Enum):
    """Pipeline processing stages.

    Each stage represents a distinct phase in article processing.
    """

    FETCH = "fetch"
    DEDUP = "dedup"
    CLASSIFY = "classify"
    CLEAN = "clean"
    CATEGORIZE = "categorize"
    VECTORIZE = "vectorize"
    CREDIBILITY = "credibility"
    ENRICH = "enrich"
    PERSIST = "persist"


# ── API Response Status Constants ──────────────────────────────


class ResponseStatus(str, enum.Enum):
    """Standard API response statuses."""

    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"


# ── Source Type Constants ──────────────────────────────────────


class SourceType(str, enum.Enum):
    """Supported data source types."""

    RSS = "rss"
    ATOM = "atom"
    HTML = "html"
    JSON = "json"


# ── Processing Status Constants ────────────────────────────────


class ProcessingStatus(str, enum.Enum):
    """Article processing status values."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"


# ── Health Status Constants ────────────────────────────────────


class HealthStatus(str, enum.Enum):
    """Service health status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


# ── LLM Provider Constants ──────────────────────────────────────


class LLMProvider(str, enum.Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    LOCAL = "local"
    ZHIPU = "zhipu"


# ── Search Mode Constants ───────────────────────────────────────


class SearchMode(str, enum.Enum):
    """Search operation modes."""

    LOCAL = "local"
    GLOBAL = "global"
    HYBRID = "hybrid"
    ARTICLES = "articles"


# ── Pipeline Task Status Constants ───────────────────────────────


class PipelineTaskStatus(str, enum.Enum):
    """Pipeline task execution status."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

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

    # LLM usage stats
    LLM_USAGE_PREFIX = "llm:usage:"

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

    @classmethod
    def from_str(cls, value: str) -> ResponseStatus:
        """Convert string to ResponseStatus enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid response status '{value}'. Valid values: {valid_values}")


# ── Source Type Constants ──────────────────────────────────────


class SourceType(str, enum.Enum):
    """Supported data source types."""

    RSS = "rss"
    ATOM = "atom"
    HTML = "html"
    JSON = "json"

    @classmethod
    def from_str(cls, value: str) -> SourceType:
        """Convert string to SourceType enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid source type '{value}'. Valid values: {valid_values}")


# ── Processing Status Constants ────────────────────────────────


class ProcessingStatus(str, enum.Enum):
    """Article processing status values."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"

    @classmethod
    def from_str(cls, value: str) -> ProcessingStatus:
        """Convert string to ProcessingStatus enum.

        Args:
            value: String value to convert.

        Returns:
            Corresponding ProcessingStatus enum member.

        Raises:
            ValueError: If value is not a valid processing status.
        """
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid processing status '{value}'. Valid values: {valid_values}")


# ── Health Status Constants ────────────────────────────────────


class HealthStatus(str, enum.Enum):
    """Service health status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

    @classmethod
    def from_str(cls, value: str) -> HealthStatus:
        """Convert string to HealthStatus enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid health status '{value}'. Valid values: {valid_values}")


# ── LLM Provider Constants ──────────────────────────────────────


class LLMProvider(str, enum.Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    LOCAL = "local"
    ZHIPU = "zhipu"
    OLLAMA = "ollama"

    @classmethod
    def from_str(cls, value: str) -> LLMProvider:
        """Convert string to LLMProvider enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid LLM provider '{value}'. Valid values: {valid_values}")


# ── Pipeline State Constants (Data Level) ───────────────────────


class ArticleProcessingState(str, enum.Enum):
    """Article processing state (data level) - represents processing stages of article data."""

    RAW = "raw"
    CLASSIFIED = "classified"
    CLEANED = "cleaned"
    VECTORIZED = "vectorized"
    ANALYZED = "analyzed"
    CREDIBILITY_SCORED = "credibility_scored"
    ENTITY_EXTRACTED = "entity_extracted"
    PERSISTED = "persisted"
    FAILED = "failed"
    DONE = "done"


# ── Graph Health Status Constants ───────────────────────────────


class GraphHealthStatus(str, enum.Enum):
    """Graph health status values."""

    HEALTHY = "healthy"
    MODERATE = "moderate"
    DEGRADED = "degraded"
    CRITICAL = "critical"

    @classmethod
    def from_str(cls, value: str) -> GraphHealthStatus:
        """Convert string to GraphHealthStatus enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid graph health status '{value}'. Valid values: {valid_values}")


# ── Sentiment Type Constants ─────────────────────────────────────


class SentimentType(str, enum.Enum):
    """Sentiment classification types."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"

    @classmethod
    def from_str(cls, value: str) -> SentimentType:
        """Convert string to SentimentType enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid sentiment type '{value}'. Valid values: {valid_values}")


# ── Search Mode Constants ───────────────────────────────────────


class SearchMode(str, enum.Enum):
    """Search operation modes."""

    LOCAL = "local"
    GLOBAL = "global"
    HYBRID = "hybrid"
    ARTICLES = "articles"

    @classmethod
    def from_str(cls, value: str) -> SearchMode:
        """Convert string to SearchMode enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid search mode '{value}'. Valid values: {valid_values}")


# ── Pipeline Task Status Constants ───────────────────────────────


class PipelineTaskStatus(str, enum.Enum):
    """Pipeline task execution status."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @classmethod
    def from_str(cls, value: str) -> PipelineTaskStatus:
        """Convert string to PipelineTaskStatus enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid pipeline task status '{value}'. Valid values: {valid_values}"
            )


# ── Relation Type Constants ────────────────────────────────────────


class RelationType(str, enum.Enum):
    """Graph relationship types between entities."""

    RELATED_TO = "RELATED_TO"
    HAS_ENTITY = "HAS_ENTITY"
    REPORTS_ON = "REPORTS_ON"
    MENTIONS = "MENTIONS"

    @classmethod
    def from_str(cls, value: str) -> RelationType:
        """Convert string to RelationType enum."""
        try:
            return cls(value.upper())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid relation type '{value}'. Valid values: {valid_values}")


# ── Health Check Status Constants ────────────────────────────────────


class HealthCheckStatus(str, enum.Enum):
    """Individual service health check status values."""

    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"
    UNAVAILABLE = "unavailable"

    @classmethod
    def from_str(cls, value: str) -> HealthCheckStatus:
        """Convert string to HealthCheckStatus enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid health check status '{value}'. Valid values: {valid_values}")


# ── Migration Status Constants ───────────────────────────────────────


class MigrationStatus(str, enum.Enum):
    """Migration operation status values."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def from_str(cls, value: str) -> MigrationStatus:
        """Convert string to MigrationStatus enum.

        Args:
            value: String value to convert.

        Returns:
            Corresponding MigrationStatus enum member.

        Raises:
            ValueError: If value is not a valid migration status.
        """
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid migration status '{value}'. Valid values: {valid_values}")


# ── Task Status Constants ────────────────────────────────────────────


class TaskStatus(str, enum.Enum):
    """Background task execution status."""

    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"
    NOT_FOUND = "not_found"

    @classmethod
    def from_str(cls, value: str) -> TaskStatus:
        """Convert string to TaskStatus enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid task status '{value}'. Valid values: {valid_values}")


# ── Default Values Constants ───────────────────────────────────────


class Defaults:
    """Default values for common operations.

    Use these constants instead of magic numbers to improve
    code readability and maintainability.
    """

    # Batch and pagination defaults
    BATCH_SIZE = 100
    LIMIT = 1000
    PAGE_SIZE = 50

    # Timeout defaults (in seconds)
    TIMEOUT_SECONDS = 30.0
    CONNECT_TIMEOUT = 10.0
    READ_TIMEOUT = 60.0

    # Buffer and chunk sizes
    BUFFER_SIZE = 1024
    CHUNK_SIZE = 8192

    # Retry defaults
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0
    RETRY_BACKOFF = 2.0

    # Cache defaults
    CACHE_TTL = 3600  # 1 hour
    CACHE_MAX_SIZE = 1000


# ── Sort Order Constants ─────────────────────────────────────────


class SortOrder(str, enum.Enum):
    """Sort order for query results."""

    ASC = "asc"
    DESC = "desc"

    @classmethod
    def from_str(cls, value: str) -> SortOrder:
        """Convert string to SortOrder enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid sort order '{value}'. Valid values: {valid_values}")


# ── Database Type Constants ──────────────────────────────────────


class DatabaseType(str, enum.Enum):
    """Database backend types."""

    POSTGRES = "postgres"
    DUCKDB = "duckdb"
    NEO4J = "neo4j"
    LADYBUG = "ladybug"
    REDIS = "redis"

    @classmethod
    def from_str(cls, value: str) -> DatabaseType:
        """Convert string to DatabaseType enum.

        Args:
            value: String value to convert.

        Returns:
            Corresponding DatabaseType enum member.

        Raises:
            ValueError: If value is not a valid database type.
        """
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid database type '{value}'. Valid values: {valid_values}")


# ── Cache Strategy Constants ─────────────────────────────────────


class CacheStrategy(str, enum.Enum):
    """Cache backend strategies."""

    REDIS = "redis"
    CASHUEWS = "cashews"
    HYBRID = "hybrid"

    @classmethod
    def from_str(cls, value: str) -> CacheStrategy:
        """Convert string to CacheStrategy enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid cache strategy '{value}'. Valid values: {valid_values}")


# ── LLM Role Constants ───────────────────────────────────────────


class LLMRole(str, enum.Enum):
    """LLM provider roles in routing."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    EMBEDDING = "embedding"

    @classmethod
    def from_str(cls, value: str) -> LLMRole:
        """Convert string to LLMRole enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid LLM role '{value}'. Valid values: {valid_values}")


# ── Embedding Model Constants ────────────────────────────────────


class EmbeddingModel(str, enum.Enum):
    """Default embedding model identifiers."""

    DEFAULT = "Qwen3-Embedding-0.6B"

    @classmethod
    def from_str(cls, value: str) -> EmbeddingModel:
        """Convert string to EmbeddingModel enum."""
        try:
            return cls(value)
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid embedding model '{value}'. Valid values: {valid_values}")


# ── Tiktoken Encoding Constants ──────────────────────────────────


class TiktokenEncoding(str, enum.Enum):
    """Tiktoken encoding names for token counting."""

    CL100K_BASE = "cl100k_base"  # Used by GPT-4, GPT-3.5-turbo, text-embedding-ada-002

    @classmethod
    def from_str(cls, value: str) -> TiktokenEncoding:
        """Convert string to TiktokenEncoding enum."""
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid tiktoken encoding '{value}'. Valid values: {valid_values}")

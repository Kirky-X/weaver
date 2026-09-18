# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Centralized string constants and enums for the weaver application.

This module provides type-safe constants for:
- Redis key prefixes and patterns
- Configuration keys
- Status values

Using enums instead of raw strings improves:
- Type safety (compile-time checking)
- IDE support (autocomplete, refactoring)
- Searchability (find all usages of a constant)
"""

from __future__ import annotations

import enum

# ── Shared User-Agent Constants ────────────────────────────────

# Chrome UA for browser-fingerprint fetchers (crawl4ai) and the Bing
# fallback; single source so fingerprint rotation stays in one place.
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Default UA for the internal fetcher (httpx fallback); keep in sync with
# the ``user_agent`` default in config/subconfigs.py via this single constant.
NEWSBOT_USER_AGENT = "Mozilla/5.0 (compatible; NewsBot/1.0)"

# ── Shared Vocabulary Constants ────────────────────────────────

# ``articles_core.document_type`` CHECK vocabulary. The SQLAlchemy model
# constraint and scripts/db.py quality checks both derive from this set;
# the Alembic migrations keep point-in-time copies on purpose.
DOCUMENT_TYPES: frozenset[str] = frozenset(
    {"news", "policy", "tweet", "wechat", "blog", "report", "pdf_doc", "social_post"}
)

# Daily briefing section categories. Single source for the briefing
# generators, analytics storage, scheduler jobs, and the briefings API.
BRIEFING_CATEGORIES: frozenset[str] = frozenset({"finance", "tech", "ai", "general"})

# Trend analysis accepted aggregation windows (days), shared by the trends
# API endpoint and the trend detection/sentiment modules.
SUPPORTED_WINDOW_DAYS: frozenset[int] = frozenset({7, 30})

# Fallback embedding model id recorded on vector rows when the caller does
# not specify one. Keep aligned with the active embedding model configured in
# config/llm.toml ([defaults.embedding]); DB column defaults cannot read TOML,
# so this constant is the deployment-neutral fallback.
DEFAULT_EMBEDDING_MODEL_ID = "text-embedding-3-large"

# PhishTank online-validation dataset download URL (security feed).
PHISHTANK_DATA_URL = "https://data.phishtank.com/data/online-valid.json"

# ASCII unit-separator used to join multi-value fields in aggregate rows
# (LLM usage aggregation, PG and DuckDB repos must agree on it).
AGG_DELIMITER = "\x1f"

# Batch size for Redis SCAN-based iterations in the analytics aggregators.
REDIS_SCAN_BATCH_SIZE = 100

# Shared retry budget for entity-merge write conflicts across the storage
# backends (base_entity_repo, neo4j entity_repo, entity_resolver).
DEFAULT_ENTITY_MERGE_RETRIES = 3

# Health-probe endpoints exempted from HMAC auth and traffic-anomaly
# accounting by the API middlewares.
HEALTH_PROBE_PATHS: frozenset[str] = frozenset({"/health", "/metrics"})

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

    # LLM analytics buffer prefixes (without trailing colon; consumers
    # append the remainder, e.g. f"{LLM_COMPARE_PREFIX}:buffer")
    LLM_COMPARE_PREFIX = "llm:compare"
    LLM_USAGE_BUFFER_PREFIX = "llm:usage"

    # Embedding cache
    EMBEDDING_PREFIX = "emb:"

    # LLM usage stats
    LLM_USAGE_PREFIX = "llm:usage:"

    @classmethod
    def crawl_retry(cls, host: str) -> str:
        """Generate retry queue key for a specific host."""
        return f"{cls.CRAWL_RETRY_PREFIX}{host}"


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
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid response status '{value}'. Valid values: {valid_values}"
            ) from _exc


# ── Source Type Constants ──────────────────────────────────────


class SourceType(str, enum.Enum):
    """Supported data source types."""

    RSS = "rss"
    ATOM = "atom"
    HTML = "html"
    JSON = "json"
    WECHAT = "wechat"
    TWITTER = "twitter"
    TELEGRAM = "telegram"
    PDF = "pdf"
    API = "api"

    @classmethod
    def from_str(cls, value: str) -> SourceType:
        """Convert string to SourceType enum."""
        try:
            return cls(value.lower())
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid source type '{value}'. Valid values: {valid_values}"
            ) from _exc


# ── Processing Status Constants ────────────────────────────────


class ProcessingStatus(str, enum.Enum):
    """Article processing status values."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    # Neo4j pending-sync completion state (pending_sync_repo.mark_synced).
    # Not an articles_core pipeline state — sync bookkeeping only.
    SYNCED = "synced"

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
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid processing status '{value}'. Valid values: {valid_values}"
            ) from _exc


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
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid health status '{value}'. Valid values: {valid_values}"
            ) from _exc


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
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid LLM provider '{value}'. Valid values: {valid_values}"
            ) from _exc


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
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid graph health status '{value}'. Valid values: {valid_values}"
            ) from _exc


# ── Circuit Breaker State Constants ─────────────────────────────


class CircuitState(str, enum.Enum):
    """Circuit breaker states, shared by the generic resilience breaker
    (``core.resilience.circuit_breaker``) and the LLM-side breaker
    (``core.llm.resilience.circuit_breaker``)."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


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
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid sentiment type '{value}'. Valid values: {valid_values}"
            ) from _exc


# ── Search Mode Constants ───────────────────────────────────────


class SearchMode(str, enum.Enum):
    """Search operation modes."""

    LOCAL = "local"
    GLOBAL = "global"
    HYBRID = "hybrid"
    DRIFT = "drift"
    LATENCY = "latency"

    @classmethod
    def from_str(cls, value: str) -> SearchMode:
        """Convert string to SearchMode enum."""
        try:
            return cls(value.lower())
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid search mode '{value}'. Valid values: {valid_values}"
            ) from _exc


# ── Unified Task Status Constants ────────────────────────────────────


class Status(str, enum.Enum):
    """Unified status for task-like lifecycles (background task / pipeline
    trigger / data migration).

    Members preserve the exact string values the former ``TaskStatus`` /
    ``PipelineTaskStatus`` / ``MigrationStatus`` enums used, so persisted and
    API-returned status strings are unchanged. The former background-task
    terminal state ``done`` was collapsed into ``COMPLETED`` ("completed");
    the in-memory task registry is its only producer and is not persisted, so
    no stored value needs migrating. ``ProcessingStatus`` / ``SagaStatus`` keep
    their own separate ``completed`` members (different lifecycles).
    """

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    NOT_FOUND = "not_found"

    @classmethod
    def from_str(cls, value: str) -> Status:
        """Convert string to Status enum."""
        try:
            return cls(value.lower())
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid status '{value}'. Valid values: {valid_values}") from _exc


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
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid health check status '{value}'. Valid values: {valid_values}"
            ) from _exc


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
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid database type '{value}'. Valid values: {valid_values}"
            ) from _exc


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
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid LLM role '{value}'. Valid values: {valid_values}") from _exc


# ── Embedding Model Constants ────────────────────────────────────


class EmbeddingModel(str, enum.Enum):
    """Default embedding model identifiers."""

    DEFAULT = "Qwen3-Embedding-0.6B"

    @classmethod
    def from_str(cls, value: str) -> EmbeddingModel:
        """Convert string to EmbeddingModel enum."""
        try:
            return cls(value)
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid embedding model '{value}'. Valid values: {valid_values}"
            ) from _exc


# ── Tiktoken Encoding Constants ──────────────────────────────────


class TiktokenEncoding(str, enum.Enum):
    """Tiktoken encoding names for token counting."""

    CL100K_BASE = "cl100k_base"  # Used by GPT-4, GPT-3.5-turbo, text-embedding-ada-002

    @classmethod
    def from_str(cls, value: str) -> TiktokenEncoding:
        """Convert string to TiktokenEncoding enum."""
        try:
            return cls(value.lower())
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid tiktoken encoding '{value}'. Valid values: {valid_values}"
            ) from _exc


# ── Language Code Constants ─────────────────────────────────────


class LanguageCode(str, enum.Enum):
    """ISO 639-1 language codes detected by the pipeline.

    Only the *resolved* languages belong here; the "language not yet
    determined" sentinel (``"unknown"``, used by ingestion/persistence
    fallbacks) is intentionally NOT a member — it is the absence of a
    language, not a language.

    spaCy model names follow the official ``{lang}_core_web_{size}``
    convention, so they are derived here as the single source of truth
    shared by :mod:`modules.processing.nlp.spacy_extractor` and
    :mod:`modules.knowledge.search.retrievers.bm25_retriever`.
    """

    ZH = "zh"
    EN = "en"

    @property
    def primary_spacy_model(self) -> str:
        """Preferred (large) spaCy pipeline used in production."""
        return f"{self.value}_core_web_lg"

    @property
    def transformer_spacy_model(self) -> str:
        """Transformer fallback (needs spacy-transformers + torch)."""
        return f"{self.value}_core_web_trf"

    @property
    def spacy_models(self) -> tuple[str, str]:
        """Ordered candidate models: primary first, transformer fallback."""
        return (self.primary_spacy_model, self.transformer_spacy_model)

    @classmethod
    def from_str(cls, value: str) -> LanguageCode:
        """Convert string to LanguageCode enum.

        Args:
            value: String value to convert.

        Returns:
            Corresponding LanguageCode enum member.

        Raises:
            ValueError: If value is not a valid language code.
        """
        try:
            return cls(value.lower())
        except ValueError as _exc:
            valid_values = [m.value for m in cls]
            raise ValueError(
                f"Invalid language code '{value}'. Valid values: {valid_values}"
            ) from _exc


# ── Entity Type Constants ──────────────────────────────────


class EntityType(str, enum.Enum):
    """Canonical entity types produced by the extraction pipeline.

    Single source of truth for the entity-type vocabulary. These match the
    categories defined in ``config/prompts/entity_extractor.toml``, the
    types stored on graph nodes, and the ``entity_type`` API filter values.
    ``entity_extractor.ALLOWED_ENTITY_TYPES`` is derived from this enum.
    """

    PERSON = "人物"
    ORGANIZATION = "组织机构"
    LOCATION = "地点"
    PRODUCT_TECH = "产品与技术"
    EVENT = "事件"
    DATA_METRIC = "数据指标"
    REGULATION = "法规与政策"
    UNKNOWN = "未知"

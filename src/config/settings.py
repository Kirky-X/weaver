# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Global application settings using pydantic-settings + TOML."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import PydanticBaseSettingsSource

from core.constants import LLMProvider

# Load environment variables from .env file
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)


class HealthCheckSettings(BaseModel):
    """Health check configuration."""

    pre_startup_enabled: bool = True
    """Enable pre-startup health checks for all services."""

    required_services: list[str] = Field(default_factory=lambda: ["postgres", "redis"])
    """Services that must be healthy for startup to proceed."""

    optional_services: list[str] = Field(default_factory=lambda: ["neo4j"])
    """Services that are checked but not required for startup."""

    timeout_seconds: float = 5.0
    """Timeout for individual service health checks."""

    max_retries: int = 3
    """Maximum number of retries for service health checks."""

    retry_delay_seconds: float = 2.0
    """Delay between retry attempts."""


class PostgresSettings(BaseSettings):
    """PostgreSQL connection settings.

    Connection details in settings.toml, password from environment.
    DSN is auto-generated from components.
    """

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", extra="ignore")

    host: str = "localhost"
    port: int = 5432
    database: str = "weaver"
    user: str = "postgres"
    password: str = ""  # Set via POSTGRES_PASSWORD environment variable

    # Pool settings
    pool_size: int = 20
    max_overflow: int = 10
    pool_timeout: float = 30.0

    @property
    def dsn(self) -> str:
        """Build DSN from components."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class Neo4jSettings(BaseSettings):
    """Neo4j connection settings.

    Reads NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_ENABLED from environment.
    """

    model_config = SettingsConfigDict(env_prefix="NEO4J_")

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "neo4j_password"
    enabled: bool = True


class DuckDBSettings(BaseSettings):
    """DuckDB fallback settings.

    Used when PostgreSQL is unavailable.
    Reads DUCKDB_ENABLED, DUCKDB_DB_PATH from environment.
    """

    model_config = SettingsConfigDict(env_prefix="DUCKDB_")

    enabled: bool = True
    db_path: str = "data/weaver.duckdb"


class LadybugSettings(BaseSettings):
    """LadybugDB (graph DB) fallback settings.

    Used when Neo4j is unavailable.
    Reads LADYBUG_ENABLED, LADYBUG_DB_PATH from environment.
    """

    model_config = SettingsConfigDict(env_prefix="LADYBUG_")

    enabled: bool = True
    db_path: str = "data/weaver_graph.ladybug"


class RedisSettings(BaseSettings):
    """Redis connection settings.

    Connection details in settings.toml, password from environment.
    URL is auto-generated from components.
    """

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""  # Set via REDIS_PASSWORD environment variable (optional)

    @property
    def url(self) -> str:
        """Build Redis URL from components."""
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class LLMSettings(BaseModel):
    """LLM module settings.

    Note: Full LLM provider and call-point configuration is in config/llm.toml.
    This class only contains embedding/rerank references for backward compatibility.
    """

    # Provider/model references (actual config is in llm.toml)
    embedding_provider: str = "aiping_embedding"
    embedding_model: str = "Qwen3-Embedding-0.6B"
    rerank_provider: str = "aiping_rerank"
    rerank_model: str = "Qwen3-Reranker-0.6B"

    @field_validator("embedding_provider", "rerank_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate that provider is a known LLMProvider value.

        Args:
            v: Provider string value.

        Returns:
            Validated provider string.

        Raises:
            ValueError: If provider is not a valid LLMProvider.
        """
        valid_providers = [p.value for p in LLMProvider]
        # Allow additional custom providers (like ollama) for flexibility
        # Only validate if it matches a known provider
        if v.lower() in valid_providers:
            return v.lower()
        # Allow custom providers (e.g., ollama, local endpoints)
        return v


class FetcherSettings(BaseModel):
    """Fetcher settings."""

    playwright_pool_size: int = 5
    default_per_host_concurrency: int = 2
    global_max_concurrency: int = 32
    httpx_timeout: float = 15.0
    user_agent: str = "Mozilla/5.0 (compatible; NewsBot/1.0)"

    stealth_enabled: bool = True
    stealth_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    stealth_viewport_width: int = 1920
    stealth_viewport_height: int = 1080
    stealth_locale: str = "zh-CN"
    stealth_timezone: str = "Asia/Shanghai"
    stealth_random_delay_min: float = 0.5
    stealth_random_delay_max: float = 2.0

    rate_limit_enabled: bool = True
    rate_limit_delay_min: float = 1.0
    rate_limit_delay_max: float = 3.0

    # Circuit breaker settings
    circuit_breaker_enabled: bool = True
    circuit_breaker_threshold: int = 5  # Consecutive failures before opening
    circuit_breaker_timeout: float = 60.0  # Cooldown period in seconds


class PromptSettings(BaseModel):
    """Prompt loading settings."""

    dir: str = str(_PROJECT_ROOT / "config" / "prompts")


class APISettings(BaseModel):
    """API layer settings."""

    api_key: str = ""  # Empty default - get_api_key() will generate if not set
    rate_limit: str = "100/minute"
    host: str = "0.0.0.0"
    port: int = 8000

    def get_api_key(self) -> str:
        """Get API key, generating one if not set.

        Returns:
            The configured API key or a securely generated random key.
        """
        if self.api_key:
            return self.api_key

        # Generate a secure random key
        generated = secrets.token_urlsafe(32)
        from core.observability.logging import get_logger

        log = get_logger("config.settings")
        log.info(
            "api_key_generated",
            message="Generated random API key (set WEAVER_API__API_KEY environment variable to override)",
            key_prefix=generated[:8] + "...",
        )
        return generated

    def validate_security(self) -> list[str]:
        """Validate security settings and return warnings.

        Returns:
            List of security warning messages.
        """
        warnings = []
        import os

        environment = os.environ.get("ENVIRONMENT", "development")

        # Use get_api_key() to check the actual key (including generated ones)
        actual_key = self.get_api_key()

        if not actual_key:
            if environment == "production":
                raise ValueError(
                    "API_KEY must be set in production environment. "
                    "Set the WEAVER_API__API_KEY environment variable."
                )
            warnings.append("Using default API key. Set WEAVER_API__API_KEY for production.")

        if len(actual_key) < 32:
            if environment == "production":
                raise ValueError("API key must be at least 32 characters in production.")
            warnings.append(
                f"API key length ({len(actual_key)}) is less than recommended 32 characters."
            )

        return warnings


class SchedulerSettings(BaseModel):
    """Unified scheduler configuration."""

    # ── Global ──────────────────────────────────────────
    enabled: bool = True
    """Master switch. False skips all APScheduler job registration."""
    misfire_grace_time_seconds: int = 300
    """Grace period for missed executions (seconds)."""
    job_timeout_seconds: int = 600
    """Max execution time per job (seconds). Exceeded → warning."""

    # ── Data Sync ───────────────────────────────────────
    crawl_interval_minutes: int = 30
    neo4j_retry_interval_minutes: int = 10
    sync_pending_to_neo4j_interval_minutes: int = 10
    retry_neo4j_writes_interval_minutes: int = 10
    sync_neo4j_with_postgres_interval_hours: int = 1
    consistency_check_cron_hour: int = 3
    consistency_check_cron_minute: int = 0

    # ── Pipeline Retry ──────────────────────────────────
    retry_flush_interval_seconds: int = 30
    pipeline_retry_interval_minutes: int = 15
    pipeline_retry_batch_size: int = 20
    pipeline_retry_dynamic_batch: bool = False
    pipeline_retry_success_rate_threshold: float = 0.8
    pipeline_retry_stuck_timeout_minutes: int = 30
    pipeline_retry_max_retries: int = 3

    # ── Cleanup ─────────────────────────────────────────
    cleanup_old_synced_days: int = 7
    cleanup_old_synced_cron_hour: int = 3
    cleanup_old_synced_cron_minute: int = 30

    llm_failure_cleanup_interval_hours: int = 24
    llm_failure_cleanup_retention_days: int = 3

    llm_usage_raw_cleanup_interval_hours: int = 6
    llm_usage_raw_retention_days: int = 2

    archive_old_neo4j_nodes_cron_day_of_week: str = "sat"
    archive_old_neo4j_nodes_cron_hour: int = 2
    archive_old_neo4j_days: int = 90

    cleanup_orphan_vectors_cron_day_of_week: str = "sat"
    cleanup_orphan_vectors_cron_hour: int = 3

    # ── Aggregation ─────────────────────────────────────
    llm_usage_aggregate_interval_minutes: int = 5
    llm_usage_redis_buffer_ttl_seconds: int = 7200

    # ── Metrics ─────────────────────────────────────────
    persist_status_metrics_interval_minutes: int = 5

    # ── Source Scoring ──────────────────────────────────
    source_auto_score_cron_hour: int = 3

    # ── Knowledge Graph ─────────────────────────────────
    community_check_interval_minutes: int = 30


class DedupSettings(BaseModel):
    """Deduplication settings."""

    enable_simhash_dedup: bool = True
    """Enable title SimHash deduplication stage."""

    simhash_hamming_threshold: int = 3
    """Maximum Hamming distance for title similarity (0-64, lower = stricter)."""


class ObservabilitySettings(BaseModel):
    """Observability settings (tracing, metrics, logging)."""

    model_config = SettingsConfigDict(env_prefix="OBS_")

    otlp_endpoint: str = "http://localhost:4317"
    """OTLP collector endpoint for OpenTelemetry tracing."""


class SearchSettings(BaseModel):
    """Search enhancement settings."""

    hybrid_enabled: bool = True
    """Enable hybrid search (vector + BM25)."""

    rerank_enabled: bool = True
    """Enable cross-encoder re-ranking."""

    rerank_model: str = "tiny"
    """Flashrank model variant (tiny, small, medium, multilingual)."""

    mmr_enabled: bool = False
    """Enable MMR diversity re-ranking."""

    mmr_lambda: float = 0.7
    """MMR lambda parameter (0-1, higher favors relevance)."""

    bm25_rebuild_interval: int = 300
    """BM25 index rebuild interval in seconds."""

    temporal_decay_enabled: bool = False
    """Enable temporal decay for search results. Newer documents receive higher scores."""

    temporal_decay_half_life_days: float = 30.0
    """Half-life in days for temporal decay. After this many days, the decay multiplier reaches 0.5."""


class IntentRoutingSettings(BaseModel):
    """Intent-aware routing configuration."""

    enabled: bool = True
    """Enable intent-aware routing."""

    classification_threshold: float = 0.7
    """Minimum confidence to use classification."""

    fallback_mode: str = "local"
    """Fallback mode if classification fails."""

    allow_explicit_mode: bool = True
    """Allow users to override with mode parameter."""


class TemporalInferenceSettings(BaseModel):
    """Temporal inference configuration."""

    enabled: bool = True
    """Enable temporal parsing."""

    default_window_days: int = 7
    """Default time window in days."""

    parse_chinese_expressions: bool = True
    """Parse Chinese relative expressions."""

    auto_anchor: bool = True
    """Automatically anchor relative times."""


class MemorySettings(BaseModel):
    """MAGMA memory system configuration.

    Controls dual-stream memory evolution parameters.
    """

    # Fast Path
    fast_path_enabled: bool = True
    """Enable synchronous event ingestion on critical path."""

    # Slow Path
    slow_path_enabled: bool = True
    """Enable asynchronous structural consolidation."""

    consolidation_interval_minutes: int = 30
    """Interval for background consolidation worker."""

    causal_confidence_threshold: float = 0.7
    """Minimum confidence for causal edges to be stored."""

    consolidation_batch_size: int = 10
    """Number of events to process per consolidation run."""

    # Retrieval
    max_traversal_depth: int = 5
    """Maximum depth for heuristic beam search."""

    beam_width: int = 10
    """Number of candidates to keep at each traversal step."""

    token_budget: int = 4000
    """Maximum tokens for retrieved context."""

    # Edge weights (λ parameters for Equation 5)
    structure_weight: float = 1.0
    """Weight for structural alignment score (λ₁)."""

    semantic_weight: float = 0.5
    """Weight for semantic similarity score (λ₂)."""

    traversal_decay: float = 0.9
    """Decay factor for cumulative traversal scores."""


def settings_customise_sources(
    settings: type[BaseSettings],
    init_settings: PydanticBaseSettingsSource,
    env_settings: PydanticBaseSettingsSource,
    dotenv_settings: PydanticBaseSettingsSource,
    file_settings: PydanticBaseSettingsSource,
) -> tuple[PydanticBaseSettingsSource, ...]:
    """Customize settings sources to include TOML file.

    Priority order (highest to lowest):
    1. init_settings (programmatic overrides)
    2. env_settings (environment variables)
    3. dotenv_settings (.env file - for secrets only)
    4. TOML file (config/settings.toml - for configuration)

    Returns:
        Tuple of settings sources in priority order.
    """
    # Use Python's built-in tomllib for reliable TOML parsing
    import tomllib

    class TomlSettingsSource(PydanticBaseSettingsSource):
        """Custom TOML settings source using tomllib."""

        def __init__(self, toml_file: Path):
            self.toml_file = toml_file
            self._toml_data: dict[str, Any] | None = None

        def __call__(self) -> dict[str, Any]:
            if self._toml_data is None:
                if self.toml_file.exists():
                    with open(self.toml_file, "rb") as f:
                        self._toml_data = tomllib.load(f)
                else:
                    self._toml_data = {}
            return self._toml_data

        def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
            """Get value for a specific field."""
            # This method is required by PydanticBaseSettingsSource
            return None, field_name, False

    toml_path = _PROJECT_ROOT / "config" / "settings.toml"
    toml_source = TomlSettingsSource(toml_file=toml_path)

    # Return tuple in priority order (highest first)
    return (
        init_settings,
        env_settings,
        dotenv_settings,
        toml_source,
    )


class Settings(BaseSettings):
    """Root application settings."""

    model_config = SettingsConfigDict(
        env_prefix="WEAVER_",
        env_nested_delimiter="__",
        extra="ignore",
        # Use default sources: env + dotenv
        # TOML will be loaded manually in __init__
    )

    app_name: str = "weaver"
    debug: bool = False

    health_check: HealthCheckSettings = Field(default_factory=HealthCheckSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    duckdb: DuckDBSettings = Field(default_factory=DuckDBSettings)
    ladybug: LadybugSettings = Field(default_factory=LadybugSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    duckdb: DuckDBSettings = Field(default_factory=DuckDBSettings)
    ladybug: LadybugSettings = Field(default_factory=LadybugSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    fetcher: FetcherSettings = Field(default_factory=FetcherSettings)
    prompt: PromptSettings = Field(default_factory=PromptSettings)
    api: APISettings = Field(default_factory=APISettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    dedup: DedupSettings = Field(default_factory=DedupSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    intent_routing: IntentRoutingSettings = Field(default_factory=IntentRoutingSettings)
    temporal_inference: TemporalInferenceSettings = Field(default_factory=TemporalInferenceSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)

    def __init__(self, **kwargs: Any) -> None:
        """Initialize settings, loading TOML config first."""
        import tomllib

        # Load TOML file first (lowest priority)
        toml_path = _PROJECT_ROOT / "config" / "settings.toml"
        toml_data: dict[str, Any] = {}

        if toml_path.exists():
            try:
                with open(toml_path, "rb") as f:
                    toml_data = tomllib.load(f)
            except Exception as e:
                import warnings

                warnings.warn(f"Failed to load TOML config: {e}", stacklevel=2)

        # Merge TOML data with defaults (TOML has lower priority than env).
        # This allows env vars to override TOML settings.
        merged_kwargs = self._deep_merge(toml_data, kwargs)

        # CRITICAL: pydantic-settings processes init_kwargs BEFORE env vars.
        # PostgreSQL: strip fields so POSTGRES_* env vars take precedence over TOML.
        import os as _os

        if _os.environ.get("POSTGRES_PASSWORD") and (
            "postgres" in merged_kwargs and isinstance(merged_kwargs["postgres"], dict)
        ):
            merged_kwargs["postgres"] = dict(merged_kwargs["postgres"])
            merged_kwargs["postgres"].pop("password", None)

        if _os.environ.get("POSTGRES_HOST") and (
            "postgres" in merged_kwargs and isinstance(merged_kwargs["postgres"], dict)
        ):
            merged_kwargs["postgres"] = dict(merged_kwargs["postgres"])
            merged_kwargs["postgres"].pop("host", None)

        # Redis: strip fields so REDIS_* env vars take precedence over TOML.
        if _os.environ.get("REDIS_PASSWORD") and (
            "redis" in merged_kwargs and isinstance(merged_kwargs["redis"], dict)
        ):
            merged_kwargs["redis"] = dict(merged_kwargs["redis"])
            merged_kwargs["redis"].pop("password", None)

        if _os.environ.get("REDIS_HOST") and (
            "redis" in merged_kwargs and isinstance(merged_kwargs["redis"], dict)
        ):
            merged_kwargs["redis"] = dict(merged_kwargs["redis"])
            merged_kwargs["redis"].pop("host", None)

        # Neo4j: strip all fields so env vars (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        # take precedence over TOML values, matching the pattern for Postgres/Redis above.
        if any(_os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")) and (
            "neo4j" in merged_kwargs and isinstance(merged_kwargs["neo4j"], dict)
        ):
            merged_kwargs["neo4j"] = dict(merged_kwargs["neo4j"])
            merged_kwargs["neo4j"].pop("uri", None)
            merged_kwargs["neo4j"].pop("user", None)
            merged_kwargs["neo4j"].pop("password", None)
            if not merged_kwargs["neo4j"]:
                merged_kwargs.pop("neo4j", None)

        # API: strip api_key so env var (WEAVER_API__API_KEY) takes precedence over TOML.
        if _os.environ.get("WEAVER_API__API_KEY") and (
            "api" in merged_kwargs and isinstance(merged_kwargs["api"], dict)
        ):
            merged_kwargs["api"] = dict(merged_kwargs["api"])
            merged_kwargs["api"].pop("api_key", None)
            if not merged_kwargs["api"]:
                merged_kwargs.pop("api", None)

        # Call parent __init__ which will process env vars and dotenv
        # with higher priority than the merged data
        super().__init__(**merged_kwargs)

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dictionaries, with override taking precedence.

        Special handling for empty strings: if override has empty string,
        still use it (to allow clearing values via env vars).
        """
        result = base.copy()

        for key, value in override.items():
            # If both are dicts, recursively merge
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = Settings._deep_merge(result[key], value)
            else:
                # Override takes precedence (including empty strings)
                result[key] = value

        return result

    def validate_security(self) -> list[str]:
        """Validate all security settings.

        Returns:
            List of security warning messages.

        Raises:
            ValueError: If production environment has insecure credentials.
        """
        warnings = []
        import os

        # Check environment
        environment = os.environ.get("ENVIRONMENT", os.environ.get("ENV", "development"))

        # Check API key security
        api_warnings = self.api.validate_security()
        warnings.extend(api_warnings)

        # Check Neo4j credentials
        if self.neo4j.password in ["neo4j_password", "your_password_here", "password", "neo4j", ""]:
            if environment == "production":
                raise ValueError(
                    "Production environment requires secure Neo4j credentials. "
                    "Set NEO4J_PASSWORD environment variable to a secure value."
                )
            warnings.append("Using default Neo4j password. Set NEO4J_PASSWORD for production.")

        # Check PostgreSQL credentials
        if not self.postgres.password or self.postgres.password in ["postgres", "password"]:
            if environment == "production":
                raise ValueError(
                    "Production environment requires secure PostgreSQL credentials. "
                    "Set POSTGRES_PASSWORD environment variable."
                )
            warnings.append(
                "Using default PostgreSQL password. Set POSTGRES_PASSWORD for production."
            )

        # Check LLM API keys are configured
        # Note: actual validation happens in container.py when loading llm.toml
        warnings.append(
            "LLM API keys should be configured in config/llm.toml with ${ENV_VAR} syntax."
        )

        return warnings

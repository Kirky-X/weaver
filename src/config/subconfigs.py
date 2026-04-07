# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Sub-configuration models for pydantic-settings.

All configuration models are defined here as pydantic BaseModel classes.
They are aggregated in Settings class in settings.py.

IMPORTANT: These classes use BaseModel (not BaseSettings) because:
- The parent Settings class handles all environment variable parsing
- Settings has env_prefix="WEAVER_" and env_nested_delimiter="__"
- This means WEAVER__POSTGRES__HOST maps to settings.postgres.host
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from pydantic import BaseModel, Field


class PostgresSettings(BaseModel):
    """PostgreSQL connection settings.

    Environment variables: WEAVER__POSTGRES__HOST, WEAVER__POSTGRES__PASSWORD, etc.
    """

    host: str = "localhost"
    port: int = 5432
    database: str = "weaver"
    user: str = "postgres"
    password: str = ""  # Set via WEAVER__POSTGRES__PASSWORD

    # Pool settings
    pool_size: int = 20
    max_overflow: int = 10
    pool_timeout: float = 30.0

    @property
    def dsn(self) -> str:
        """Build DSN from components."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class Neo4jSettings(BaseModel):
    """Neo4j connection settings.

    Environment variables: WEAVER__NEO4J__URI, WEAVER__NEO4J__USER, WEAVER__NEO4J__PASSWORD, WEAVER__NEO4J__ENABLED
    """

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = ""  # Set via WEAVER__NEO4J__PASSWORD
    enabled: bool = True


class DuckDBSettings(BaseModel):
    """DuckDB fallback settings.

    Environment variables: WEAVER__DUCKDB__ENABLED, WEAVER__DUCKDB__DB_PATH
    """

    enabled: bool = True
    db_path: str = "data/weaver.duckdb"


class LadybugSettings(BaseModel):
    """LadybugDB (graph DB) fallback settings.

    Environment variables: WEAVER__LADYBUG__ENABLED, WEAVER__LADYBUG__DB_PATH
    """

    enabled: bool = True
    db_path: str = "data/weaver_graph.ladybug"


class RedisSettings(BaseModel):
    """Redis connection settings.

    Environment variables: WEAVER__REDIS__HOST, WEAVER__REDIS__PORT, WEAVER__REDIS__PASSWORD, etc.
    """

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""  # Set via WEAVER__REDIS__PASSWORD (optional)

    @property
    def url(self) -> str:
        """Build Redis URL from components."""
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class APISettings(BaseModel):
    """API layer settings.

    Environment variables: WEAVER__API__API_KEY, WEAVER__API__HOST, WEAVER__API__PORT, etc.
    """

    api_key: str = ""  # Empty default - get_api_key() will generate if not set
    rate_limit: str = "100/minute"
    host: str = "127.0.0.1"  # Default to localhost for security
    port: int = 8000
    port_auto_detect: bool = True  # Enable automatic port detection
    port_max_attempts: int = 100  # Maximum port search attempts

    def get_api_key(self) -> str:
        """Get API key, generating one if not set."""
        if self.api_key:
            return self.api_key

        # Generate a secure random key
        generated = secrets.token_urlsafe(32)
        from core.observability.logging import get_logger

        log = get_logger("config.settings")
        log.info(
            "api_key_generated",
            message="Generated random API key (set WEAVER__API__API_KEY environment variable to override)",
            key_prefix=generated[:8] + "...",
        )
        return generated

    def validate_security(self) -> list[str]:
        """Validate security settings and return warnings."""
        warnings = []
        environment = os.environ.get("ENVIRONMENT", "development")

        actual_key = self.get_api_key()

        if not actual_key:
            if environment == "production":
                raise ValueError(
                    "API_KEY must be set in production environment. "
                    "Set the WEAVER__API__API_KEY environment variable."
                )
            warnings.append("Using default API key. Set WEAVER__API__API_KEY for production.")

        if len(actual_key) < 32:
            if environment == "production":
                raise ValueError("API key must be at least 32 characters in production.")
            warnings.append(
                f"API key length ({len(actual_key)}) is less than recommended 32 characters."
            )

        return warnings

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization hook to resolve port if auto-detect is enabled."""
        if self.port_auto_detect:
            self._resolve_port()

    def _resolve_port(self) -> None:
        """Resolve and update to an available port if needed."""
        from core.net.port_announcer import PortAnnouncer
        from core.net.port_finder import PortFinder

        original_port = self.port
        write_env = os.getenv("WEAVER_WRITE_PORT_ENV", "false").lower() in ("true", "1", "yes")

        if PortFinder.is_port_available(self.host, self.port):
            announcer = PortAnnouncer(write_env_file=write_env)
            announcer.announce(self.host, self.port, original_port)
            return

        try:
            available_port = PortFinder.find_available_port(
                host=self.host,
                start_port=self.port,
                max_attempts=self.port_max_attempts,
            )
            self.port = available_port
            announcer = PortAnnouncer(write_env_file=write_env)
            announcer.announce(self.host, available_port, original_port)
        except Exception as e:
            from core.observability.logging import get_logger

            log = get_logger("config.settings")
            log.error(
                "port_resolution_failed",
                host=self.host,
                port=self.port,
                error=str(e),
            )
            raise


class SchedulerSettings(BaseModel):
    """Unified scheduler configuration."""

    # Global
    enabled: bool = True
    misfire_grace_time_seconds: int = 300
    job_timeout_seconds: int = 600

    # Data Sync
    crawl_interval_minutes: int = 30
    neo4j_retry_interval_minutes: int = 10
    sync_pending_to_neo4j_interval_minutes: int = 10
    retry_neo4j_writes_interval_minutes: int = 10
    sync_neo4j_with_postgres_interval_hours: int = 1
    consistency_check_cron_hour: int = 3
    consistency_check_cron_minute: int = 0

    # Pipeline Retry
    retry_flush_interval_seconds: int = 30
    pipeline_retry_interval_minutes: int = 15
    pipeline_retry_batch_size: int = 20
    pipeline_retry_dynamic_batch: bool = False
    pipeline_retry_success_rate_threshold: float = 0.8
    pipeline_retry_stuck_timeout_minutes: int = 30
    pipeline_retry_max_retries: int = 3

    # Cleanup
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

    # Aggregation
    llm_usage_aggregate_interval_minutes: int = 5
    llm_usage_redis_buffer_ttl_seconds: int = 7200

    # Metrics
    persist_status_metrics_interval_minutes: int = 5

    # Source Scoring
    source_auto_score_cron_hour: int = 3

    # Knowledge Graph
    community_check_interval_minutes: int = 30


class FetcherSettings(BaseModel):
    """Fetcher settings."""

    default_per_host_concurrency: int = 2
    global_max_concurrency: int = 32
    httpx_timeout: float = 15.0
    user_agent: str = "Mozilla/5.0 (compatible; NewsBot/1.0)"

    # crawl4ai browser settings
    crawl4ai_headless: bool = True
    crawl4ai_stealth_enabled: bool = True
    crawl4ai_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    crawl4ai_timeout: float = 30.0

    rate_limit_enabled: bool = True
    rate_limit_delay_min: float = 1.0
    rate_limit_delay_max: float = 3.0

    # Circuit breaker settings
    circuit_breaker_enabled: bool = True
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 60.0


class SearchSettings(BaseModel):
    """Search enhancement settings."""

    hybrid_enabled: bool = True
    rerank_enabled: bool = True
    rerank_model: str = "tiny"
    mmr_enabled: bool = False
    mmr_lambda: float = 0.7
    bm25_rebuild_interval: int = 300
    temporal_decay_enabled: bool = False
    temporal_decay_half_life_days: float = 30.0


class DedupSettings(BaseModel):
    """Deduplication settings."""

    enable_simhash_dedup: bool = True
    simhash_hamming_threshold: int = 3


class ObservabilitySettings(BaseModel):
    """Observability settings (tracing, metrics, logging).

    Environment variables: WEAVER__OBSERVABILITY__OTLP_ENDPOINT
    """

    otlp_endpoint: str = ""


class MemorySettings(BaseModel):
    """MAGMA memory system configuration."""

    fast_path_enabled: bool = True
    slow_path_enabled: bool = True
    consolidation_interval_minutes: int = 30
    causal_confidence_threshold: float = 0.7
    consolidation_batch_size: int = 10
    max_traversal_depth: int = 5
    beam_width: int = 10
    token_budget: int = 4000
    structure_weight: float = 1.0
    semantic_weight: float = 0.5
    traversal_decay: float = 0.9


class SpacySettings(BaseModel):
    """spaCy model detection and installation settings."""

    force_install: bool = False
    strict_mode: bool = True
    models: list[str] = Field(default_factory=lambda: ["zh_core_web_lg", "en_core_web_sm"])
    local_paths: dict[str, str] = Field(default_factory=dict)


class URLSecuritySettings(BaseModel):
    """URL security check configuration."""

    enabled: bool = True
    urlhaus_api_key: str = ""
    urlhaus_api_timeout: float = 5.0
    phishtank_enabled: bool = True
    phishtank_data_url: str = "https://data.phishtank.com/data/online-valid.json"
    phishtank_sync_interval_hours: int = 6
    phishtank_data_path: str = "data/phishtank.json"
    heuristic_enabled: bool = True
    heuristic_check_encoded_chars: bool = True
    heuristic_check_suspicious_keywords: bool = True
    heuristic_check_domain_structure: bool = True
    ssl_verify_enabled: bool = True
    ssl_verify_timeout: float = 10.0
    cache_enabled: bool = True
    cache_safe_ttl_seconds: int = 21600
    cache_malicious_ttl_seconds: int = 900


class EntitySettings(BaseModel):
    """Entity extraction configuration."""

    disable_data_metrics_nodes: bool = False


class HealthCheckSettings(BaseModel):
    """Health check configuration."""

    pre_startup_enabled: bool = True
    required_services: list[str] = Field(default_factory=lambda: ["postgres", "redis"])
    optional_services: list[str] = Field(default_factory=lambda: ["neo4j"])
    timeout_seconds: float = 5.0
    max_retries: int = 3
    retry_delay_seconds: float = 2.0


class PromptSettings(BaseModel):
    """Prompt loading settings."""

    dir: str = "config/prompts"


class IntentRoutingSettings(BaseModel):
    """Intent-aware routing configuration."""

    enabled: bool = True
    classification_threshold: float = 0.7
    fallback_mode: str = "local"
    allow_explicit_mode: bool = True


class TemporalInferenceSettings(BaseModel):
    """Temporal inference configuration."""

    enabled: bool = True
    default_window_days: int = 7
    parse_chinese_expressions: bool = True
    auto_anchor: bool = True


class PipelineUrlEndpointSettings(BaseModel):
    """Single URL pipeline processing endpoint configuration."""

    whitelist_enabled: bool = False
    allowed_domains: list[str] = Field(default_factory=list)

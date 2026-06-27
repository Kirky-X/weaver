# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Sub-configuration models for pydantic-settings.

All configuration models are defined here as pydantic BaseModel classes.
They are aggregated in Settings class in settings.py.

IMPORTANT: These classes use BaseModel (not BaseSettings) because:
- The parent Settings class handles all environment variable parsing
- Settings has env_prefix="WEAVER_" and env_nested_delimiter="__"
- This means WEAVER_POSTGRES__HOST maps to settings.postgres.host
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from pydantic import BaseModel, Field

from core.utils.paths import CONFIG_DIR, DATA_DIR, data_path


class PostgresSettings(BaseModel):
    """PostgreSQL connection settings.

    Environment variables: WEAVER_POSTGRES__HOST, WEAVER_POSTGRES__PASSWORD, etc.
    """

    host: str = "localhost"
    port: int = 5432
    database: str = "weaver"
    user: str = "postgres"
    password: str = ""  # Set via WEAVER_POSTGRES__PASSWORD

    # Pool settings
    pool_size: int = 20
    max_overflow: int = 10
    pool_timeout: float = 30.0

    @property
    def dsn(self) -> str:
        """Build DSN from components."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    def pgbouncer_dsn(self, pgbouncer_host: str, pgbouncer_port: int) -> str:
        """Build DSN pointing to PgBouncer proxy instead of direct PostgreSQL.

        Args:
            pgbouncer_host: PgBouncer proxy hostname.
            pgbouncer_port: PgBouncer proxy port.

        Returns:
            DSN string pointing to PgBouncer.
        """
        return f"postgresql+asyncpg://{self.user}:{self.password}@{pgbouncer_host}:{pgbouncer_port}/{self.database}"


class Neo4jSettings(BaseModel):
    """Neo4j connection settings.

    Environment variables: WEAVER_NEO4J__URI, WEAVER_NEO4J__USER, WEAVER_NEO4J__PASSWORD, WEAVER_NEO4J__ENABLED
    """

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = ""  # Set via WEAVER_NEO4J__PASSWORD
    enabled: bool = True


class DuckDBSettings(BaseModel):
    """DuckDB fallback settings.

    Environment variables: WEAVER_DUCKDB__ENABLED, WEAVER_DUCKDB__DB_PATH
    """

    enabled: bool = True
    db_path: str = data_path("weaver.duckdb")


class LadybugSettings(BaseModel):
    """LadybugDB (graph DB) fallback settings.

    Environment variables: WEAVER_LADYBUG__ENABLED, WEAVER_LADYBUG__DB_PATH
    """

    enabled: bool = True
    db_path: str = data_path("weaver.lbug")


class RedisSettings(BaseModel):
    """Redis connection settings.

    Environment variables: WEAVER_REDIS__HOST, WEAVER_REDIS__PORT, WEAVER_REDIS__PASSWORD, etc.
    """

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""  # Set via WEAVER_REDIS__PASSWORD (optional)
    scan_count: int = 100  # Default Redis SCAN batch size

    @property
    def url(self) -> str:
        """Build Redis URL from components."""
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class APISettings(BaseModel):
    """API layer settings.

    Environment variables: WEAVER_API__API_KEY, WEAVER_API__HOST, WEAVER_API__PORT, etc.
    """

    api_key: str = ""  # Empty default - get_api_key() will generate if not set
    admin_api_key: str = ""  # Optional admin key for sensitive endpoints
    rate_limit: str = "100/minute"
    host: str = "127.0.0.1"  # Default to localhost for security
    port: int = 8000
    port_auto_detect: bool = True  # Enable automatic port detection
    port_max_attempts: int = 100  # Maximum port search attempts
    require_auth_for_metrics: bool = False  # Optional auth for Prometheus metrics endpoint
    hmac_signing_enabled: bool = False  # Enable HMAC signature verification middleware
    hmac_secret: str | None = (
        None  # Independent HMAC signing key (WEAVER_API__HMAC_SECRET). Falls back to API key if not set.
    )
    shutdown_timeout: float = 30.0  # Pipeline drain timeout during shutdown

    def get_api_key(self) -> str:
        """Get API key, generating one if not set."""
        if self.api_key:
            return self.api_key

        # Generate a secure random key
        generated = secrets.token_urlsafe(32)
        from core.observability import get_logger

        log = get_logger(__name__)
        log.info(
            "api_key_generated",
            message="Generated random API key (set WEAVER_API__API_KEY environment variable to override)",
            key_prefix=generated[:8] + "...",
        )
        return generated

    def validate_security(self, environment: str = "development") -> list[str]:
        """Validate security settings and return warnings."""
        warnings = []
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

        # Validate admin API key if configured
        if self.admin_api_key and len(self.admin_api_key) < 32:
            if environment == "production":
                raise ValueError("Admin API key must be at least 32 characters in production.")
            warnings.append(
                f"Admin API key length ({len(self.admin_api_key)}) is less than recommended 32 characters."
            )

        # Warn if admin key not configured in production
        if not self.admin_api_key and environment == "production":
            warnings.append(
                "Admin API key not configured. Sensitive endpoints (/config) will require regular API key. "
                "Set WEAVER_API__ADMIN_API_KEY for proper admin access control."
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
            from core.observability import get_logger

            log = get_logger(__name__)
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

    # Pipeline B — Enrichment
    enrichment_interval_minutes: int = 5

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

    # Batch sizes for sync jobs
    consistency_check_batch_size: int = 100  # For get_incomplete_articles
    sync_pending_batch_size: int = 100  # For get_pending sync

    # Aggregation
    llm_usage_aggregate_interval_minutes: int = 5
    llm_usage_redis_buffer_ttl_seconds: int = 7200

    # Metrics
    persist_status_metrics_interval_minutes: int = 5

    # Source Scoring
    source_auto_score_cron_hour: int = 3

    # Knowledge Graph
    community_check_interval_minutes: int = 30

    # PhishTank Sync
    sync_phishtank_interval_hours: int = 6


class FetcherSettings(BaseModel):
    """Fetcher settings."""

    default_per_host_concurrency: int = 2
    global_max_concurrency: int = 32
    httpx_timeout: float = 15.0
    user_agent: str = "Mozilla/5.0 (compatible; NewsBot/1.0)"

    # crawl4ai browser settings (used by init_smart_fetcher)
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

    rerank_enabled: bool = True
    rerank_model: str = "tiny"
    mmr_enabled: bool = True
    mmr_lambda: float = 0.7
    mmr_similarity_mode: str = "jaccard"
    global_map_community_timeout: float = 15.0
    global_map_overall_timeout: float = 30.0
    global_reduce_timeout: float = 15.0


class ObservabilitySettings(BaseModel):
    """Observability settings (tracing, metrics, logging).

    Environment variables: WEAVER_OBSERVABILITY__OTLP_ENDPOINT
    """

    otlp_endpoint: str = ""
    log_file: str = ""
    log_rotation: str = "10 MB"
    log_retention: str = "7 days"


class MemorySettings(BaseModel):
    """MAGMA memory system configuration."""

    fast_path_enabled: bool = True
    slow_path_enabled: bool = True
    consolidation_interval_minutes: int = 30
    causal_confidence_threshold: float = 0.7
    consolidation_batch_size: int = 10
    # Temporal chain query limits for adaptive search
    temporal_chain_why_limit: int = 5  # WHY query anchor limit
    temporal_chain_when_limit: int = 3  # WHEN query anchor limit
    temporal_chain_default_limit: int = 3  # Default anchor limit
    temporal_chain_event_lookup_limit: int = 1000  # Event data lookup limit
    max_traversal_depth: int = 5
    beam_width: int = 10
    token_budget: int = 4000
    max_relations_per_entity: int = 50  # Max causal relations per entity


class SpacySettings(BaseModel):
    """spaCy model detection and installation settings."""

    force_install: bool = False
    strict_mode: bool = True
    models: list[str] = Field(default_factory=lambda: ["zh_core_web_lg", "en_core_web_lg"])
    local_paths: dict[str, str] = Field(default_factory=dict)
    # Local model paths for runtime loading (wheel file or directory)
    zh_model_path: str | None = None
    en_model_path: str | None = None


class URLSecuritySettings(BaseModel):
    """URL security check configuration."""

    enabled: bool = True
    urlhaus_api_key: str = ""
    urlhaus_api_timeout: float = 5.0
    phishtank_enabled: bool = True
    phishtank_data_url: str = "https://data.phishtank.com/data/online-valid.json"
    phishtank_sync_interval_hours: int = 6
    phishtank_data_path: str = data_path("phishtank.json")
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
    """Entity extraction and resolution configuration."""

    disable_data_metrics_nodes: bool = False
    resolution_candidate_limit: int = 10  # Vector search candidate limit for entity resolution


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

    dir: str = str(CONFIG_DIR / "prompts")


class TemporalMemorySettings(BaseModel):
    """Temporal memory query limits for adaptive search."""

    why_anchor_limit: int = 5
    when_anchor_limit: int = 3
    default_anchor_limit: int = 3
    event_lookup_limit: int = 1000


class PipelineUrlEndpointSettings(BaseModel):
    """Single URL pipeline processing endpoint configuration."""

    whitelist_enabled: bool = False
    allowed_domains: list[str] = Field(default_factory=list)


class PipelineProcessSettings(BaseModel):
    """Pipeline processing configuration."""

    merge_cross_query_limit: int = 20  # Cross-query similar articles limit
    drain_timeout: float = 30.0  # Pipeline drain timeout
    worker_poll_interval: float = 1.0  # seconds between queue polls
    worker_batch_size: int = 5  # items per batch (reduced from 20 to speed up first-batch response)
    worker_error_delay: float = 5.0  # seconds after error


class KnowledgeCacheSettings(BaseModel):
    """Knowledge cluster cache configuration.

    Environment variables: WEAVER_KNOWLEDGE_CACHE__PATH, WEAVER_KNOWLEDGE_CACHE__MAX_QUERIES
    """

    path: str = str(DATA_DIR / ".cache" / "knowledge")
    sync_interval: int = 60  # Seconds between Parquet syncs
    sync_threshold: int = 100  # Dirty count triggering immediate sync
    max_queries: int = 5  # FIFO queue size per cluster
    similarity_threshold: float = 0.85  # Minimum similarity for cache hit
    hotness_threshold: float = 0.3  # Minimum hotness to keep cluster


class DailyBriefingSettings(BaseModel):
    """Daily briefing generation configuration.

    Environment variables: WEAVER__DAILY_BRIEFING__MAX_ITEMS, etc.
    """

    max_items: int = 10
    max_per_category: int = 3
    lookback_hours: int = 24


class SagaSettings(BaseModel):
    """Saga compensation transaction configuration.

    Environment variables: WEAVER_SAGA__TIMEOUT_SECONDS, etc.
    """

    timeout_seconds: int = 300  # Maximum saga execution time
    max_retries: int = 3  # Maximum retry attempts per step
    retry_base_delay: float = 1.0  # Base delay for exponential backoff
    retry_max_delay: float = 30.0  # Maximum delay for exponential backoff
    compensation_timeout: int = 120  # Timeout per compensation operation
    log_retention_days: int = 30  # Days to retain saga logs before archival


class FakeNewsDetectorSettings(BaseModel):
    """Fake news detector configuration (5-dimensional feature fusion).

    Environment variables: WEAVER_ANALYTICS__FAKE_NEWS_DETECTOR__ENABLED, etc.
    """

    enabled: bool = True
    model_path: str = ""  # Empty = rule-based fallback
    confidence_trusted: float = 0.8
    confidence_suspicious: float = 0.4
    clickbait_similarity_threshold: float = 0.5
    exaggeration_keywords: list[str] = Field(
        default_factory=lambda: ["震惊", "惊天", "竟然", "不敢相信", "绝密", "曝光"]
    )


class PaddleNLPSentimentSettings(BaseModel):
    """PaddleNLP SKEP sentiment analysis configuration.

    Environment variables: WEAVER__PADDLENLP__SENTIMENT__ENABLED, etc.
    """

    enabled: bool = True
    model_name: str = "skep_ernie_1.0_large_chinese"
    max_input_length: int = 512
    confidence_threshold: float = 0.6
    fallback_to_llm: bool = True


class TrafficAnomalySettings(BaseModel):
    """Traffic anomaly detection configuration.

    Environment variables: WEAVER_TRAFFIC_ANOMALY__ENABLED, etc.
    """

    enabled: bool = False
    default_key_rate_limit: int = 200
    ip_rate_limit: int = 200
    burst_threshold: int = 10
    ip_ban_duration_seconds: int = 900


class VaultSettings(BaseModel):
    """HashiCorp Vault integration configuration.

    When enabled, sensitive configuration values (passwords, API keys)
    are retrieved from Vault instead of environment variables.

    Environment variables: WEAVER_VAULT__ENABLED, WEAVER_VAULT__URL, WEAVER_VAULT__TOKEN, etc.

    Deployment:
        1. Start Vault server: vault server -dev (dev) or production config
        2. Store secrets: vault kv put secret/weaver/postgres password=xxx
        3. Configure Weaver: set WEAVER_VAULT__ENABLED=true and WEAVER_VAULT__TOKEN
        4. Weaver will fetch secrets from Vault at startup
    """

    enabled: bool = False
    url: str = "http://localhost:8200"
    token: str = ""  # Set via WEAVER_VAULT__TOKEN
    mount_path: str = "secret/weaver"
    secret_keys: list[str] = Field(
        default_factory=lambda: [
            "postgres/password",
            "neo4j/password",
            "redis/password",
            "api/api_key",
            "api/admin_api_key",
        ]
    )


class PgBouncerSettings(BaseModel):
    """PgBouncer connection pooler configuration.

    When enabled, PostgreSQL connections are routed through PgBouncer
    for improved connection management in production deployments.

    Environment variables: WEAVER_PGBOUNCER__ENABLED, WEAVER_PGBOUNCER__HOST, etc.

    Deployment:
        1. Install PgBouncer: apt install pgbouncer (Ubuntu) or equivalent
        2. Configure PgBouncer: set auth_type, database connection strings
        3. Configure Weaver: set WEAVER_PGBOUNCER__ENABLED=true
        4. Weaver will connect to PgBouncer instead of PostgreSQL directly

    Note: PgBouncer operates at the infrastructure level. Weaver only needs
    to point its DSN to the PgBouncer proxy address.
    """

    enabled: bool = False
    host: str = "localhost"
    port: int = 6432
    pool_mode: str = "transaction"  # session / transaction / statement

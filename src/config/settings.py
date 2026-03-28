# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Global application settings using pydantic-settings + TOML."""

from __future__ import annotations

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


class PostgresSettings(BaseModel):
    """PostgreSQL connection settings."""

    dsn: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver"


class Neo4jSettings(BaseSettings):
    """Neo4j connection settings.

    Reads NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD from environment.
    """

    model_config = SettingsConfigDict(env_prefix="NEO4J_")

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "neo4j_password"


class RedisSettings(BaseModel):
    """Redis connection settings."""

    url: str = "redis://localhost:6379/0"


class LLMSettings(BaseModel):
    """LLM module settings.

    Note: Full LLM provider and call-point configuration is in config/llm.toml.
    This class only contains simplified references used by specific components.
    """

    # Provider/model references (actual config is in llm.toml)
    embedding_provider: str = "aiping_embedding"
    embedding_model: str = "Qwen3-Embedding-0.6B"
    rerank_provider: str = "aiping_rerank"
    rerank_model: str = "Qwen3-Reranker-0.6B"

    # Legacy fields - kept for backwards compatibility
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    call_points: dict[str, dict[str, Any]] = Field(default_factory=dict)

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

    api_key: str = "change-me-in-production"
    rate_limit: str = "100/minute"
    host: str = "0.0.0.0"
    port: int = 8000

    def validate_security(self) -> list[str]:
        """Validate security settings and return warnings.

        Returns:
            List of security warning messages.
        """
        warnings = []
        import os

        environment = os.environ.get("ENVIRONMENT", "development")

        if self.api_key in ["change-me-in-production", ""]:
            if environment == "production":
                raise ValueError(
                    "API_KEY must be set in production environment. "
                    "Set the WEAVER_API__API_KEY environment variable."
                )
            warnings.append("Using default API key. Set WEAVER_API__API_KEY for production.")

        if len(self.api_key) < 32:
            if environment == "production":
                raise ValueError("API key must be at least 32 characters in production.")
            warnings.append(
                f"API key length ({len(self.api_key)}) is less than recommended 32 characters."
            )

        return warnings


class SchedulerSettings(BaseModel):
    """APScheduler settings."""

    crawl_interval_minutes: int = 30
    neo4j_retry_interval_minutes: int = 10
    retry_flush_interval_seconds: int = 30


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
        # Use default sources: env + dotenv
        # TOML will be loaded manually in __init__
    )

    app_name: str = "weaver"
    debug: bool = False

    health_check: HealthCheckSettings = Field(default_factory=HealthCheckSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    fetcher: FetcherSettings = Field(default_factory=FetcherSettings)
    prompt: PromptSettings = Field(default_factory=PromptSettings)
    api: APISettings = Field(default_factory=APISettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    dedup: DedupSettings = Field(default_factory=DedupSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    search: SearchSettings = Field(default_factory=SearchSettings)

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
        # If we pass postgres={"dsn": "toml_value"} as init kwargs, pydantic
        # cannot override it with WEAVER_POSTGRES__DSN from the environment.
        # Fix: when WEAVER_POSTGRES__DSN is set in the environment, remove the
        # postgres.dsn from merged_kwargs so pydantic can read it from env vars.
        import os as _os

        if _os.environ.get("WEAVER_POSTGRES__DSN") and (
            "postgres" in merged_kwargs and isinstance(merged_kwargs["postgres"], dict)
        ):
            merged_kwargs["postgres"] = dict(merged_kwargs["postgres"])
            merged_kwargs["postgres"].pop("dsn", None)
            if not merged_kwargs["postgres"]:
                merged_kwargs.pop("postgres", None)

        # Redis: strip url so env vars (WEAVER_REDIS__URL) take precedence over TOML.
        if _os.environ.get("WEAVER_REDIS__URL") and (
            "redis" in merged_kwargs and isinstance(merged_kwargs["redis"], dict)
        ):
            merged_kwargs["redis"] = dict(merged_kwargs["redis"])
            merged_kwargs["redis"].pop("url", None)
            if not merged_kwargs["redis"]:
                merged_kwargs.pop("redis", None)

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
        if self.neo4j.password in ["neo4j_password", "your_password_here", "password", "neo4j"]:
            if environment == "production":
                raise ValueError(
                    "Production environment requires secure Neo4j credentials. "
                    "Set NEO4J_PASSWORD environment variable to a secure value."
                )
            warnings.append("Using default Neo4j password. Set NEO4J_PASSWORD for production.")

        # Check PostgreSQL credentials
        if "postgres:postgres@" in self.postgres.dsn or ":@localhost" in self.postgres.dsn:
            if environment == "production":
                raise ValueError(
                    "Production environment requires secure PostgreSQL credentials. "
                    "Set POSTGRES_PASSWORD environment variable or use a secure DSN."
                )
            warnings.append(
                "Using default PostgreSQL credentials. Set POSTGRES_PASSWORD for production."
            )

        # Check LLM API keys
        openai_config = self.llm.providers.get("openai", {})
        openai_api_key = openai_config.get("api_key", "")

        if not openai_api_key or openai_api_key == "":
            if environment == "production":
                raise ValueError(
                    "Production environment requires LLM API key. "
                    "Set LLM_API_KEY_OPENAI or WEAVER_LLM__PROVIDERS__OPENAI__API_KEY environment variable."
                )
            warnings.append("LLM API key not set. Set LLM_API_KEY_OPENAI for production.")

        return warnings

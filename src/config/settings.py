# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Global application settings using pydantic-settings + TOML.

Configuration Priority (highest to lowest):
1. Environment variables
2. .env file (for secrets)
3. TOML configuration files (config/settings.toml, config/llm.toml, config/pipeline.toml)
4. Code defaults

Environment Variable Format:
- Prefix: WEAVER_ (single underscore)
- Nested delimiter: __ (double underscore)
- Format: WEAVER_<TOP_LEVEL>__<NESTED_FIELD>

Examples:
- WEAVER_APP_NAME=myapp           → settings.app_name
- WEAVER_POSTGRES__HOST=localhost → settings.postgres.host
- WEAVER_NEO4J__PASSWORD=secret   → settings.neo4j.password
- WEAVER_API__API_KEY=your_key    → settings.api.api_key
- WEAVER_LLM__PROVIDERS__AIPING__API_KEY=sk-xxx → settings.llm.providers.aiping.api_key
"""

from __future__ import annotations

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# Import sub-configurations
from config.subconfigs import (
    APISettings,
    DailyBriefingSettings,
    DuckDBSettings,
    EntitySettings,
    FakeNewsDetectorSettings,
    FetcherSettings,
    HealthCheckSettings,
    LadybugSettings,
    MemorySettings,
    Neo4jSettings,
    ObservabilitySettings,
    PaddleNLPSentimentSettings,
    PgBouncerSettings,
    PipelineProcessSettings,
    PipelineUrlEndpointSettings,
    PostgresSettings,
    PromptSettings,
    RedisSettings,
    SagaSettings,
    SchedulerSettings,
    SearchSettings,
    SpacySettings,
    TemporalMemorySettings,
    TrafficAnomalySettings,
    URLSecuritySettings,
)
from core.llm.config.config import LLMSettings
from core.utils.paths import PROJECT_ROOT
from modules.processing.pipeline.config import PipelineSettings

# Load environment variables from .env file
load_dotenv(PROJECT_ROOT / ".env", override=False)


class Settings(BaseSettings):
    """Root application settings.

    Aggregates all sub-configurations with unified environment variable support.
    Configuration files are loaded from config/settings.toml.

    LLM configuration is loaded from config/llm.toml via LLMSettings.
    Pipeline configuration is loaded from config/pipeline.toml via PipelineSettings.
    """

    model_config = SettingsConfigDict(
        toml_file=str(PROJECT_ROOT / "config" / "settings.toml"),
        env_prefix="WEAVER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Application metadata
    app_name: str = "weaver"
    environment: str = "development"  # development / staging / production
    debug: bool = False

    # Sub-configurations (loaded from TOML, can be overridden by env vars)
    health_check: HealthCheckSettings = Field(default_factory=HealthCheckSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    duckdb: DuckDBSettings = Field(default_factory=DuckDBSettings)
    ladybug: LadybugSettings = Field(default_factory=LadybugSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    api: APISettings = Field(default_factory=APISettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    fetcher: FetcherSettings = Field(default_factory=FetcherSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    spacy: SpacySettings = Field(default_factory=SpacySettings)
    url_security: URLSecuritySettings = Field(default_factory=URLSecuritySettings)
    entity: EntitySettings = Field(default_factory=EntitySettings)
    prompt: PromptSettings = Field(default_factory=PromptSettings)
    temporal_memory: TemporalMemorySettings = Field(default_factory=TemporalMemorySettings)
    pipeline_url_endpoint: PipelineUrlEndpointSettings = Field(
        default_factory=PipelineUrlEndpointSettings
    )
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    pipeline_process: PipelineProcessSettings = Field(default_factory=PipelineProcessSettings)

    # Analytics settings (loaded from TOML)
    daily_briefing: DailyBriefingSettings = Field(default_factory=DailyBriefingSettings)
    saga: SagaSettings = Field(default_factory=SagaSettings)
    paddlenlp_sentiment: PaddleNLPSentimentSettings = Field(
        default_factory=PaddleNLPSentimentSettings
    )
    fake_news_detector: FakeNewsDetectorSettings = Field(default_factory=FakeNewsDetectorSettings)
    traffic_anomaly: TrafficAnomalySettings = Field(default_factory=TrafficAnomalySettings)

    # Infrastructure integration settings (disabled by default)
    pgbouncer: PgBouncerSettings = Field(default_factory=PgBouncerSettings)

    # LLM configuration (loaded from separate TOML file)
    llm: LLMSettings = Field(default_factory=LLMSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customize settings sources with TOML support.

        Priority order (highest to lowest):
        1. Environment variables (env_settings)
        2. Programmatic overrides (init_settings)
        3. .env file (dotenv_settings)
        4. TOML configuration file (TomlConfigSettingsSource)
        """
        return (
            env_settings,  # Highest priority: environment variables
            init_settings,  # Programmatic overrides
            dotenv_settings,  # .env file for secrets
            TomlConfigSettingsSource(settings_cls),  # TOML file
        )

    def validate_security(self) -> list[str]:
        """Validate all security settings.

        Returns:
            List of security warning messages.

        Raises:
            ValueError: If production environment has insecure credentials.
        """
        warnings = []
        environment = self.environment

        # Check API key security
        api_warnings = self.api.validate_security(environment=self.environment)
        warnings.extend(api_warnings)

        # Check Neo4j credentials
        if self.neo4j.password in ["neo4j_password", "your_password_here", "password", "neo4j", ""]:
            if environment == "production":
                raise ValueError(
                    "Production environment requires secure Neo4j credentials. "
                    "Set WEAVER_NEO4J__PASSWORD environment variable to a secure value."
                )
            warnings.append(
                "Using default Neo4j password. Set WEAVER_NEO4J__PASSWORD for production."
            )

        # Check PostgreSQL credentials
        if not self.postgres.password or self.postgres.password in ["postgres", "password"]:
            if environment == "production":
                raise ValueError(
                    "Production environment requires secure PostgreSQL credentials. "
                    "Set WEAVER_POSTGRES__PASSWORD environment variable."
                )
            warnings.append(
                "Using default PostgreSQL password. Set WEAVER_POSTGRES__PASSWORD for production."
            )

        # Check LLM API keys
        warnings.append(
            "LLM API keys should be configured via WEAVER_LLM__PROVIDERS__<NAME>__API_KEY environment variable."
        )

        return warnings


def get_settings() -> Settings:
    """Get the global settings instance.

    Delegates to container.get_settings() for unified singleton management.
    Creates a new Settings instance if container is not initialized.

    Returns:
        Settings instance.
    """
    try:
        from container import get_settings as container_get_settings

        return container_get_settings()
    except Exception:
        from core.observability import get_logger

        log = get_logger(__name__)
        log.warning(
            "settings_container_not_initialized",
            message="Container not initialized when get_settings() called. Creating standalone Settings instance.",
        )
        return Settings()

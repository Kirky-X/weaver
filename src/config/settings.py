"""Global application settings using pydantic-settings + TOML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import PydanticBaseSettingsSource

# Load environment variables from .env file
load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class PostgresSettings(BaseSettings):
    """PostgreSQL connection settings."""

    dsn: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/news_discovery"


class Neo4jSettings(BaseSettings):
    """Neo4j connection settings."""

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "neo4j_password"

    @property
    def auth(self) -> tuple[str, str]:
        """Return auth as tuple for Neo4j driver."""
        return (self.user, self.password)


class RedisSettings(BaseSettings):
    """Redis connection settings."""

    url: str = "redis://localhost:6379/0"


class LLMProviderConfig(BaseSettings):
    """Single LLM provider configuration."""

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    rpm_limit: int = 60
    concurrency: int = 5
    timeout: float = 30.0


class LLMCallPointConfig(BaseSettings):
    """Call-point level LLM configuration (primary + fallbacks)."""

    primary: str = "openai"
    fallbacks: list[str] = Field(default_factory=list)


class LLMSettings(BaseSettings):
    """LLM module settings."""

    providers: dict[str, dict[str, Any]] = Field(default_factory=lambda: {
        "openai": {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "rpm_limit": 60,
            "concurrency": 5,
            "timeout": 120.0,
        },
        "ollama": {
            "provider": "ollama",
            "model": "qwen3.5:9b",
            "api_key": "",
            "base_url": "http://172.24.160.1:11434",
            "rpm_limit": 60,
            "concurrency": 3,
            "timeout": 300.0,
        },
    })
    call_points: dict[str, dict[str, Any]] = Field(default_factory=lambda: {
        "classifier": {"primary": "ollama", "fallbacks": ["openai"]},
        "cleaner": {"primary": "ollama", "fallbacks": ["openai"]},
        "categorizer": {"primary": "ollama", "fallbacks": ["openai"]},
        "merger": {"primary": "ollama", "fallbacks": ["openai"]},
        "analyze": {"primary": "ollama", "fallbacks": ["openai"]},
        "credibility_checker": {"primary": "ollama", "fallbacks": ["openai"]},
        "entity_extractor": {"primary": "ollama", "fallbacks": ["openai"]},
        "entity_resolver": {"primary": "ollama", "fallbacks": ["openai"]},
    })
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-large"
    rerank_provider: str = "openai"
    rerank_model: str = ""


class FetcherSettings(BaseSettings):
    """Fetcher settings."""

    playwright_pool_size: int = 5
    default_per_host_concurrency: int = 2
    global_max_concurrency: int = 32
    httpx_timeout: float = 15.0
    user_agent: str = "Mozilla/5.0 (compatible; NewsBot/1.0)"


class PromptSettings(BaseSettings):
    """Prompt loading settings."""

    dir: str = str(_PROJECT_ROOT / "src" / "config" / "prompts")


class APISettings(BaseSettings):
    """API layer settings."""

    api_key: str = "change-me-in-production"
    rate_limit: str = "100/minute"
    host: str = "0.0.0.0"
    port: int = 8000


class SchedulerSettings(BaseSettings):
    """APScheduler settings."""

    crawl_interval_minutes: int = 30
    neo4j_retry_interval_minutes: int = 10
    retry_flush_interval_seconds: int = 30


def settings_customize_settings(
    settings: type[BaseSettings],
    init_settings: PydanticBaseSettingsSource,
    env_settings: PydanticBaseSettingsSource,
    dotenv_settings: PydanticBaseSettingsSource,
    file_settings: PydanticBaseSettingsSource,
) -> dict[str, PydanticBaseSettingsSource]:
    """Customize settings sources to include TOML file."""
    from pydantic_settings.sources import TomlConfigSettingsSource

    toml_path = _PROJECT_ROOT / "src" / "config" / "settings.toml"
    toml_source = TomlConfigSettingsSource(
        settings_class=settings,
        toml_file_path=str(toml_path),
    )

    return {
        "env": env_settings,
        "toml": toml_source,
    }


class Settings(BaseSettings):
    """Root application settings."""

    model_config = SettingsConfigDict(
        env_prefix="ND_",
        env_nested_delimiter="__",
        settings_customise_sources=settings_customize_settings,
    )

    app_name: str = "news-discovery"
    debug: bool = False

    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    fetcher: FetcherSettings = Field(default_factory=FetcherSettings)
    prompt: PromptSettings = Field(default_factory=PromptSettings)
    api: APISettings = Field(default_factory=APISettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)

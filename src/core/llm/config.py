# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM configuration using pydantic-settings for TOML loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from core.llm.types import (
    GlobalConfig,
    ModelConfig,
    ProviderConfig,
    RoutingConfig,
)
from core.observability.logging import get_logger

log = get_logger("llm_config")

# Project root for config file paths
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class LLMSettings(BaseSettings):
    """LLM configuration loaded from config/llm.toml.

    Supports two-layer nested configuration:
    - Layer 1: Provider configuration (aiping, dmx, ollama, etc.)
    - Layer 2: Model configuration (nested under each provider)

    Environment variables can override any setting using WEAVER_LLM__ prefix.
    For provider-specific settings: WEAVER_LLM__PROVIDERS__<NAME>__API_KEY
    """

    model_config = SettingsConfigDict(
        toml_file=str(_PROJECT_ROOT / "config" / "llm.toml"),
        env_prefix="WEAVER_LLM__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Global settings
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 60.0
    default_timeout: float = 120.0

    # Provider configurations (dynamic keys)
    providers: dict[str, ProviderConfig] = {}

    # Default routing
    defaults: dict[str, RoutingConfig] = {}

    # Call-point routing (maps from TOML "call-points" key)
    call_points: dict[str, RoutingConfig] = {}

    @field_validator("providers", mode="before")
    @classmethod
    def parse_providers(cls, v: Any) -> dict[str, ProviderConfig]:
        """Parse providers from TOML nested structure."""
        if v is None:
            return {}
        if isinstance(v, dict):
            result: dict[str, ProviderConfig] = {}
            for name, cfg in v.items():
                if isinstance(cfg, ProviderConfig):
                    result[name] = cfg
                elif isinstance(cfg, dict):
                    # Parse nested models
                    models_data = cfg.get("models", {})
                    models: dict[str, ModelConfig] = {}
                    for model_name, model_cfg in models_data.items():
                        if isinstance(model_cfg, ModelConfig):
                            models[model_name] = model_cfg
                        elif isinstance(model_cfg, dict):
                            models[model_name] = ModelConfig(**model_cfg)

                    result[name] = ProviderConfig(
                        name=name,
                        type=cfg.get("type", "openai"),
                        api_key=cfg.get("api_key", ""),
                        base_url=cfg.get("base_url", ""),
                        rpm_limit=cfg.get("rpm_limit", 60),
                        concurrency=cfg.get("concurrency", 5),
                        timeout=cfg.get("timeout", 120.0),
                        priority=cfg.get("priority", 100),
                        weight=cfg.get("weight", 100),
                        models=models,
                    )
            return result
        return {}

    @field_validator("defaults", "call_points", mode="before")
    @classmethod
    def parse_routing_dict(cls, v: Any) -> dict[str, RoutingConfig]:
        """Parse routing config dict."""
        if v is None:
            return {}
        if isinstance(v, dict):
            result: dict[str, RoutingConfig] = {}
            for key, val in v.items():
                if isinstance(val, RoutingConfig):
                    result[key] = val
                elif isinstance(val, dict):
                    result[key] = RoutingConfig(**val)
            return result
        return {}

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Configure source priority: env > init > TOML."""
        return (
            env_settings,  # Highest priority: environment variables
            init_settings,  # Programmatic overrides
            TomlConfigSettingsSource(settings_cls),  # TOML file
        )

    def __init__(self, **data: Any) -> None:
        """Initialize with TOML data, handling hyphenated keys."""
        # Load TOML manually to handle hyphenated keys
        import tomllib

        toml_path = _PROJECT_ROOT / "config" / "llm.toml"
        if toml_path.exists():
            with open(toml_path, "rb") as f:
                toml_data = tomllib.load(f)

            # Map hyphenated keys to underscored keys
            if "call-points" in toml_data and "call_points" not in data:
                data["call_points"] = toml_data["call-points"]

        super().__init__(**data)

    def get_global_config(self) -> GlobalConfig:
        """Get GlobalConfig for backward compatibility with LLMClient."""
        return GlobalConfig(
            circuit_breaker_threshold=self.circuit_breaker_threshold,
            circuit_breaker_timeout=self.circuit_breaker_timeout,
            default_timeout=self.default_timeout,
            defaults=self.defaults,
            call_points=self.call_points,
        )

    def get_providers(self) -> list[ProviderConfig]:
        """Get list of ProviderConfig for backward compatibility with LLMClient."""
        return list(self.providers.values())


# Convenience function for backward compatibility
def load_llm_config(config_path: str | None = None) -> tuple[list[ProviderConfig], GlobalConfig]:
    """Load LLM configuration from TOML file.

    Args:
        config_path: Optional path to config file (ignored, uses pydantic-settings).

    Returns:
        Tuple of (providers list, global config) for backward compatibility.
    """
    settings = LLMSettings()
    log.info(
        "llm_config_loaded",
        providers=len(settings.providers),
        defaults=len(settings.defaults),
        call_points=len(settings.call_points),
    )
    return settings.get_providers(), settings.get_global_config()

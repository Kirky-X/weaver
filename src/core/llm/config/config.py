# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""LLM configuration using pydantic-settings for TOML loading."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from core.llm.types import (
    EvalConfig,
    ModelConfig,
    ProviderConfig,
    RoutingConfig,
    RoutingMode,
    parse_routing_dict_shared,
)
from core.observability import get_logger
from core.utils.paths import PROJECT_ROOT

log = get_logger("llm_config")


class LLMSettings(BaseSettings):
    """LLM configuration loaded from config/llm.toml.

    Supports two-layer nested configuration:
    - Layer 1: Provider configuration (aiping, dmx, ollama, etc.)
    - Layer 2: Model configuration (nested under each provider)

    Environment variables can override any setting using WEAVER_LLM__ prefix.
    For provider-specific settings: WEAVER_LLM__PROVIDERS__<NAME>__API_KEY
    """

    model_config = SettingsConfigDict(
        toml_file=str(PROJECT_ROOT / "config" / "llm.toml"),
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

    # Per-call-point routing mode and weights
    routing: dict[str, dict[str, Any]] = {}

    # Shadow evaluation config
    eval_config: EvalConfig = Field(default_factory=EvalConfig)

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
        """Parse routing config dict (delegates to shared function)."""
        return parse_routing_dict_shared(v)

    @field_validator("routing", mode="before")
    @classmethod
    def parse_routing(cls, v: Any) -> dict[str, dict[str, Any]]:
        """Parse per-call-point routing configuration."""
        if v is None:
            return {}
        if isinstance(v, dict):
            result: dict[str, dict[str, Any]] = {}
            for key, val in v.items():
                if isinstance(val, dict):
                    # Normalize mode string
                    mode = val.get("mode", "auto")
                    if isinstance(mode, str):
                        try:
                            mode = RoutingMode(mode).value
                        except ValueError:
                            mode = "auto"
                    result[key] = {
                        "mode": mode,
                        "weights": val.get("weights", {}),
                        "bandit": val.get("bandit", {}),
                    }
            return result
        return {}

    @field_validator("eval_config", mode="before")
    @classmethod
    def parse_eval_config(cls, v: Any) -> EvalConfig:
        """Parse shadow evaluation configuration."""
        if v is None:
            return EvalConfig()
        if isinstance(v, EvalConfig):
            return v
        if isinstance(v, dict):
            return EvalConfig(
                enabled=v.get("enabled", False),
                sample_rate=v.get("sample_rate", 0.1),
                target_call_points=tuple(v.get("target_call_points", [])),
                baseline_model=v.get("baseline_model", ""),
                candidate_models=tuple(v.get("candidate_models", [])),
            )
        return EvalConfig()

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

        toml_path = PROJECT_ROOT / "config" / "llm.toml"
        if toml_path.exists():
            with open(toml_path, "rb") as f:
                toml_data = tomllib.load(f)

            # Map hyphenated keys to underscored keys
            if "call-points" in toml_data and "call_points" not in data:
                data["call_points"] = toml_data["call-points"]

        super().__init__(**data)

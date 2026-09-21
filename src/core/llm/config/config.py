# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""LLM configuration using pydantic-settings for TOML loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from core.llm.config.cost import CostConfig
from core.llm.types import (
    EMBEDDING_CACHE_TTL,
    DEFAULT_LLM_TIMEOUT,
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
    default_timeout: float = DEFAULT_LLM_TIMEOUT
    # LLM call retry policy ([global] in llm.toml)
    retry_max_attempts: int = 3
    retry_min_wait: float = 5.0
    retry_max_wait: float = 60.0
    # Embedding response-cache TTL (seconds)
    embedding_cache_ttl: int = EMBEDDING_CACHE_TTL
    # Cached rerank-client ceiling (FIFO eviction; safety bound)
    rerank_client_cap: int = 32
    # 全局请求延迟（llm.toml [global] 映射；provider 级可覆盖）
    request_delay_enabled: bool = False
    request_delay_min: float = 1.0
    request_delay_max: float = 2.0

    # Provider configurations (dynamic keys)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)

    # Default routing
    defaults: dict[str, RoutingConfig] = Field(default_factory=dict)

    # Per-call-point input truncation limits (characters), overrides the
    # built-in defaults by call-point name (see core.llm.client._INPUT_LIMITS).
    input_limits: dict[str, int] = Field(default_factory=dict)

    # Call-point routing (maps from TOML "call-points" key)
    call_points: dict[str, RoutingConfig] = Field(default_factory=dict)

    # Per-call-point routing mode and weights
    routing: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Shadow evaluation config
    eval_config: EvalConfig = Field(default_factory=EvalConfig)

    # Cost rates for LLM usage accounting.
    # Default empty CostConfig → CostCalculator not instantiated.
    # To enable cost tracking: set WEAVER_LLM__COST__RATES__<LABEL>__INPUT
    # and WEAVER_LLM__COST__RATES__<LABEL>__OUTPUT env vars, or extend
    # llm.toml with a [cost] section (AGENTS.md forbids editing llm.toml
    # during this change; future extension TBD).
    cost: CostConfig = Field(default_factory=CostConfig)

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
                        timeout=cfg.get("timeout"),
                        priority=cfg.get("priority", 100),
                        weight=cfg.get("weight", 100),
                        models=models,
                        request_delay_enabled=cfg.get("request_delay_enabled"),
                        request_delay_min=cfg.get("request_delay_min"),
                        request_delay_max=cfg.get("request_delay_max"),
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

    def __init__(self, toml_path: Path | None = None, **data: Any) -> None:
        """Initialize with TOML data, handling hyphenated keys.

        toml_path 仅供测试注入临时配置文件；默认读项目 config/llm.toml。
        注意：以 ``**toml_dict`` 形式注入时，dict 里的嵌套 ``[global]``/``[eval]``
        表不会被消费（extra="ignore" 丢弃）——顶层映射只针对本方法读到的
        config_path 文件。热重载路径（live_config）传入的正是同一项目文件，
        因此值一致；不要用 **data 形式注入外来嵌套配置。
        """
        # Load TOML manually to handle hyphenated keys
        import tomllib

        config_path = toml_path if toml_path is not None else PROJECT_ROOT / "config" / "llm.toml"
        if config_path.exists():
            with open(config_path, "rb") as f:
                toml_data = tomllib.load(f)

            # Map hyphenated keys to underscored keys
            if "call-points" in toml_data and "call_points" not in data:
                data["call_points"] = toml_data["call-points"]

            # Map [eval] section → eval_config (same TOML-source limitation
            # as [global]: without this, the documented [eval] table is a
            # zombie config that never loads).
            if "eval" in toml_data and "eval_config" not in data:
                data["eval_config"] = toml_data["eval"]

            # extra="ignore" would silently drop any other hyphenated
            # top-level section; surface it so config typos are visible.
            known_hyphenated = {"call-points"}
            unexpected = [k for k in toml_data if "-" in k and k not in known_hyphenated]
            if unexpected:
                log.warning(
                    "llm_config_unexpected_hyphenated_keys",
                    keys=sorted(unexpected),
                )

            # Map [global] section → top-level fields. pydantic-settings 的
            # TOML source 只映射顶层键，[global] 表会被静默丢弃（僵尸配置）：
            # 改 [global] 永不生效。显式映射使熔断阈值/超时/请求延迟/重试/
            # 缓存 TTL/rerank 上限可配置。
            global_cfg = toml_data.get("global", {})
            if isinstance(global_cfg, dict):
                for key in (
                    "circuit_breaker_threshold",
                    "circuit_breaker_timeout",
                    "default_timeout",
                    "request_delay_enabled",
                    "request_delay_min",
                    "request_delay_max",
                    "retry_max_attempts",
                    "retry_min_wait",
                    "retry_max_wait",
                    "embedding_cache_ttl",
                    "rerank_client_cap",
                ):
                    if key in global_cfg and key not in data:
                        data[key] = global_cfg[key]

        super().__init__(**data)

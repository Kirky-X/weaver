# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""配置加载器，支持两层嵌套配置格式."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from core.llm.types import (
    Capability,
    GlobalConfig,
    LLMType,
    ModelConfig,
    ProviderConfig,
    RoutingConfig,
)
from core.observability.logging import get_logger

log = get_logger("llm_config")


class ConfigLoadError(Exception):
    """配置加载错误."""

    pass


class LLMConfigLoader:
    """LLM配置加载器.

    支持两层嵌套配置格式:
    - 第一层: Provider厂商配置
    - 第二层: 模型配置（嵌套在provider下）
    """

    @classmethod
    def load(cls, config_path: str) -> tuple[list[ProviderConfig], GlobalConfig]:
        """加载配置文件.

        Args:
            config_path: 配置文件路径

        Returns:
            (providers列表, 全局配置)

        Raises:
            ConfigLoadError: 配置加载失败
        """
        path = Path(config_path)
        if not path.exists():
            raise ConfigLoadError(f"Config file not found: {config_path}")

        with open(path, "rb") as f:
            config = tomllib.load(f)

        # 解析全局配置
        global_config = cls._parse_global_config(config)

        # 解析provider配置
        providers = cls._parse_providers(config)

        log.info(
            "config_loaded",
            path=config_path,
            providers=len(providers),
            defaults=len(global_config.defaults),
            call_points=len(global_config.call_points),
        )

        return providers, global_config

    @classmethod
    def _parse_global_config(cls, config: dict[str, Any]) -> GlobalConfig:
        """解析全局配置."""
        global_section = config.get("global", {})

        # 解析defaults
        defaults: dict[LLMType, RoutingConfig] = {}
        defaults_section = config.get("defaults", {})
        for type_name, routing_cfg in defaults_section.items():
            try:
                llm_type = LLMType(type_name)
                defaults[llm_type] = RoutingConfig(
                    primary=routing_cfg.get("label", ""),
                    fallbacks=routing_cfg.get("fallbacks", []),
                )
            except ValueError:
                log.warning("unknown_default_type", type=type_name)

        # 解析call-points
        call_points: dict[str, RoutingConfig] = {}
        call_points_section = config.get("call-points", {})
        for cp_name, routing_cfg in call_points_section.items():
            call_points[cp_name] = RoutingConfig(
                primary=routing_cfg.get("primary", ""),
                fallbacks=routing_cfg.get("fallbacks", []),
            )

        return GlobalConfig(
            circuit_breaker_threshold=global_section.get("circuit_breaker_threshold", 5),
            circuit_breaker_timeout=global_section.get("circuit_breaker_timeout", 60.0),
            default_timeout=global_section.get("default_timeout", 120.0),
            defaults=defaults,
            call_points=call_points,
        )

    @classmethod
    def _parse_providers(cls, config: dict[str, Any]) -> list[ProviderConfig]:
        """解析provider配置."""
        providers_section = config.get("providers", {})
        providers: list[ProviderConfig] = []

        for provider_name, provider_cfg in providers_section.items():
            try:
                provider = cls._parse_provider(provider_name, provider_cfg)
                providers.append(provider)
            except Exception as e:
                log.error(
                    "provider_parse_failed",
                    provider=provider_name,
                    error=str(e),
                )
                raise ConfigLoadError(f"Failed to parse provider '{provider_name}': {e}") from e

        return providers

    @classmethod
    def _parse_provider(cls, name: str, cfg: dict[str, Any]) -> ProviderConfig:
        """解析单个provider配置."""
        # 解析API Key(支持环境变量引用)
        api_key = cfg.get("api_key", "")
        api_key = cls._resolve_env_var(api_key)

        # 解析模型配置(嵌套)
        models: dict[str, ModelConfig] = {}
        models_section = cfg.get("models", {})
        for model_name, model_cfg in models_section.items():
            models[model_name] = cls._parse_model(model_cfg)

        return ProviderConfig(
            name=name,
            type=cfg.get("type", "openai"),
            api_key=api_key,
            base_url=cfg.get("base_url", ""),
            rpm_limit=cfg.get("rpm_limit", 60),
            concurrency=cfg.get("concurrency", 5),
            timeout=cfg.get("timeout", 120.0),
            priority=cfg.get("priority", 100),
            weight=cfg.get("weight", 100),
            models=models,
        )

    @classmethod
    def _parse_model(cls, cfg: dict[str, Any]) -> ModelConfig:
        """解析模型配置."""
        # 解析capabilities
        capabilities_list = cfg.get("capabilities", [])
        capabilities = frozenset(Capability(c.strip()) for c in capabilities_list if c.strip())

        return ModelConfig(
            model_id=cfg.get("model_id", ""),
            temperature=cfg.get("temperature", 0.0),
            max_tokens=cfg.get("max_tokens"),
            capabilities=capabilities,
        )

    @classmethod
    def _resolve_env_var(cls, value: str) -> str:
        """解析环境变量引用.

        支持格式: ${ENV_VAR} 或 ${ENV_VAR:-default}
        """
        if not value.startswith("${"):
            return value

        # 提取环境变量名
        inner = value[2:-1]  # 移除 ${ 和 }

        # 支持默认值语法: ${VAR:-default}
        if ":-" in inner:
            var_name, default = inner.split(":-", 1)
            return os.environ.get(var_name, default)

        return os.environ.get(inner, "")

"""Multi-provider LLM configuration manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.observability.logging import get_logger

log = get_logger("llm_config")


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""

    provider: str
    model: str
    api_key: str
    base_url: str
    rpm_limit: int = 60
    concurrency: int = 5
    timeout: float = 30.0


@dataclass
class CallPointConfig:
    """Configuration for a specific call point (primary + fallback chain)."""

    primary: ProviderConfig
    primary_name: str  # Store the provider name, not just the type
    fallbacks: list[ProviderConfig] = field(default_factory=list)
    fallback_names: list[str] = field(default_factory=list)  # Store fallback names


class LLMConfigManager:
    """Parses and manages multi-provider LLM configurations.

    Reads provider and call-point configurations from the settings
    and provides lookup methods for the queue manager.
    """

    def __init__(self, config: Any) -> None:
        """Initialize from LLM settings.

        Args:
            config: LLMSettings object with providers and call_points dicts.
        """
        self._providers: dict[str, ProviderConfig] = {}
        self._call_points: dict[str, CallPointConfig] = {}

        # Default provider config
        default_provider = {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "rpm_limit": 60,
            "concurrency": 5,
            "timeout": 30.0,
        }

        # Parse provider configs - merge with defaults
        providers_dict = config.providers if isinstance(config.providers, dict) else {}
        log.debug("providers_dict", providers_keys=list(providers_dict.keys()))
        for name, pcfg in providers_dict.items():
            if isinstance(pcfg, dict):
                # Merge with default config
                merged_config = {**default_provider, **pcfg}
                # Ensure numeric fields are properly typed
                merged_config["rpm_limit"] = int(merged_config.get("rpm_limit", 60))
                merged_config["concurrency"] = int(merged_config.get("concurrency", 5))
                merged_config["timeout"] = float(merged_config.get("timeout", 30.0))
                self._providers[name] = ProviderConfig(**merged_config)
            else:
                self._providers[name] = pcfg

        # Parse call-point configs
        call_points_dict = config.call_points if isinstance(config.call_points, dict) else {}
        for cp_name, cp_cfg in call_points_dict.items():
            if isinstance(cp_cfg, dict):
                primary_name = cp_cfg.get("primary", "openai")
                fallback_names = cp_cfg.get("fallbacks", [])
                # Handle case where fallbacks is a string instead of a list
                if isinstance(fallback_names, str):
                    fallback_names = [fb.strip() for fb in fallback_names.split(",") if fb.strip()]
            else:
                primary_name = cp_cfg.primary
                fallback_names = cp_cfg.fallbacks
                # Handle case where fallbacks is a string instead of a list
                if isinstance(fallback_names, str):
                    fallback_names = [fb.strip() for fb in fallback_names.split(",") if fb.strip()]

            primary = self._providers.get(primary_name)
            if not primary:
                log.warning(
                    "call_point_primary_not_found",
                    call_point=cp_name,
                    primary=primary_name,
                )
                continue

            fallbacks = [self._providers[fb] for fb in fallback_names if fb in self._providers]

            self._call_points[cp_name] = CallPointConfig(
                primary=primary,
                primary_name=primary_name,
                fallbacks=fallbacks,
                fallback_names=list(fallback_names),
            )

        log.info(
            "llm_config_loaded",
            providers=list(self._providers.keys()),
            call_points=list(self._call_points.keys()),
        )

        # Store embedding configuration
        self._embedding_provider = getattr(config, "embedding_provider", "openai")
        self._embedding_model = getattr(config, "embedding_model", "text-embedding-3-large")
        log.info(
            "embedding_config",
            provider=self._embedding_provider,
            model=self._embedding_model,
        )

    def list_providers(self) -> list[tuple[str, ProviderConfig]]:
        """List all configured providers.

        Returns:
            List of (name, config) tuples.
        """
        return list(self._providers.items())

    def get_provider(self, name: str) -> ProviderConfig:
        """Get a specific provider config.

        Args:
            name: Provider name.

        Returns:
            The provider configuration.

        Raises:
            KeyError: If provider not found.
        """
        return self._providers[name]

    def get_call_point_config(self, call_point: str) -> CallPointConfig:
        """Get the call-point configuration (primary + fallbacks).

        Args:
            call_point: Call point name (e.g. 'classifier').

        Returns:
            The call point configuration with primary and fallback chain.

        Raises:
            KeyError: If call point not configured.
        """
        cp = call_point.value if hasattr(call_point, "value") else call_point
        return self._call_points[cp]

    def get_embedding_config(self) -> tuple[str, str, ProviderConfig] | None:
        """Get the embedding provider configuration.

        Returns:
            Tuple of (provider_name, model, ProviderConfig) or None if not configured.
        """
        provider_name = self._embedding_provider
        if provider_name not in self._providers:
            log.warning("embedding_provider_not_found", provider=provider_name)
            return None

        return (
            provider_name,
            self._embedding_model,
            self._providers[provider_name],
        )

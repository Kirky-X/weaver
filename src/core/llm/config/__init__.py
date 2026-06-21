# Copyright (c) 2026 KirkyX. All Rights Reserved

from __future__ import annotations

from pydantic import BaseModel

from core.llm.config.config import LLMSettings
from core.llm.config.live_config import ConfigReloadError, LiveConfig
from core.llm.config.token_budget import TokenBudgetManager


class CostRate(BaseModel):
    """Cost rate for a model (USD per 1K tokens)."""

    input: float = 0.0
    output: float = 0.0
    cached: float = 1.0  # fraction of input rate for cached tokens


class CostConfig(BaseModel):
    """Cost configuration loaded from TOML."""

    currency: str = "USD"
    rates: dict[str, CostRate] = {}
    default: CostRate = CostRate()

    def lookup(self, label: str) -> CostRate:
        """Look up cost rate for a label, falling back to default."""
        return self.rates.get(label, self.default)


__all__ = [
    "ConfigReloadError",
    "CostConfig",
    "CostRate",
    "LLMSettings",
    "LiveConfig",
    "TokenBudgetManager",
]

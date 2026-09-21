# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""LLM cost rate configuration models.

Defines per-model token cost rates (USD per 1K tokens) loaded from TOML.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CostRate(BaseModel):
    """Cost rate for a model (USD per 1K tokens).

    Frozen so ``CostConfig.lookup`` can safely return the shared ``default``
    instance without callers mutating it for everyone else.
    """

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    input: float = Field(default=0.0, ge=0)
    output: float = Field(default=0.0, ge=0)
    # fraction of input rate for cached tokens (must stay within [0, 1])
    cached: float = Field(default=1.0, ge=0, le=1)


class CostConfig(BaseModel):
    """Cost configuration loaded from TOML."""

    currency: str = "USD"
    rates: dict[str, CostRate] = {}
    default: CostRate = CostRate()

    def lookup(self, label: str) -> CostRate:
        """Look up cost rate for a label, falling back to default."""
        return self.rates.get(label, self.default)

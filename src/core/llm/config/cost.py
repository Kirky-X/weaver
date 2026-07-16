# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""LLM cost rate configuration models.

Defines per-model token cost rates (USD per 1K tokens) loaded from TOML.
"""

from __future__ import annotations

from pydantic import BaseModel


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

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""LLM cost calculator service."""

from __future__ import annotations

from core.llm.config import CostConfig
from core.llm.types import TokenUsage


class CostCalculator:
    """Calculates USD cost from token usage and cost rates."""

    def __init__(self, config: CostConfig) -> None:
        self._config = config

    def calculate(
        self,
        label: str,
        tokens: TokenUsage,
    ) -> float:
        """Calculate cost in USD for a single LLM call.

        Args:
            label: The LLM label string (e.g. "chat.openai.gpt-4o").
            tokens: Token usage from the call.

        Returns:
            Cost in USD, rounded to 10 decimal places.
        """
        rate = self._config.lookup(label)
        effective_input = max(0, tokens.input_tokens - tokens.cached_tokens)
        input_cost = (effective_input / 1000.0) * rate.input
        cached_cost = (tokens.cached_tokens / 1000.0) * rate.input * rate.cached
        output_cost = (tokens.output_tokens / 1000.0) * rate.output
        return round(input_cost + cached_cost + output_cost, 10)

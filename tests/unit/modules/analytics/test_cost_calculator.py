# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for CostCalculator.calculate() scenarios.

Test 5.4:
- Standard call: input=1000, output=500, rate input=0.0025 output=0.01 -> cost = 0.0075
- Cached tokens: input=1000, cached=300, rate input=0.0025 cached=0.5 -> cost = 0.002125
- Unknown model uses default rate
- Zero tokens returns 0
"""

import pytest

from core.llm.config import CostConfig, CostRate
from core.llm.types import TokenUsage
from modules.analytics.llm_usage.cost_calculator import CostCalculator


class TestCostCalculatorStandardCall:
    """Standard cost calculation without caching."""

    def test_standard_call_cost(self):
        """input=1000, output=500, input_rate=0.0025, output_rate=0.01 -> cost=0.0075."""
        config = CostConfig(
            rates={
                "chat.openai.gpt-4o": CostRate(input=0.0025, output=0.01, cached=1.0),
            }
        )
        calc = CostCalculator(config)
        tokens = TokenUsage(input_tokens=1000, output_tokens=500)

        cost = calc.calculate("chat.openai.gpt-4o", tokens)

        # input_cost = (1000 / 1000) * 0.0025 = 0.0025
        # cached_cost = (0 / 1000) * 0.0025 * 1.0 = 0.0
        # output_cost = (500 / 1000) * 0.01 = 0.005
        # total = 0.0025 + 0.0 + 0.005 = 0.0075
        assert cost == pytest.approx(0.0075, abs=1e-10)

    def test_standard_call_only_input(self):
        """Only input tokens, no output."""
        config = CostConfig(
            rates={
                "model": CostRate(input=0.01, output=0.03, cached=1.0),
            }
        )
        calc = CostCalculator(config)
        tokens = TokenUsage(input_tokens=2000, output_tokens=0)

        cost = calc.calculate("model", tokens)

        # (2000/1000) * 0.01 = 0.02
        assert cost == pytest.approx(0.02, abs=1e-10)

    def test_standard_call_only_output(self):
        """Only output tokens, no input."""
        config = CostConfig(
            rates={
                "model": CostRate(input=0.01, output=0.03, cached=1.0),
            }
        )
        calc = CostCalculator(config)
        tokens = TokenUsage(input_tokens=0, output_tokens=1000)

        cost = calc.calculate("model", tokens)

        # (1000/1000) * 0.03 = 0.03
        assert cost == pytest.approx(0.03, abs=1e-10)


class TestCostCalculatorCachedTokens:
    """Cost calculation with cached tokens."""

    def test_cached_tokens_reduced_input_cost(self):
        """Cached tokens reduce effective input cost.

        input=1000, cached=300, input_rate=0.0025, cached_rate=0.5:
        effective_input = 1000 - 300 = 700
        input_cost = (700/1000) * 0.0025 = 0.00175
        cached_cost = (300/1000) * 0.0025 * 0.5 = 0.000375
        output_cost = 0
        total = 0.00175 + 0.000375 = 0.002125
        """
        config = CostConfig(
            rates={
                "model": CostRate(input=0.0025, output=0.01, cached=0.5),
            }
        )
        calc = CostCalculator(config)
        tokens = TokenUsage(input_tokens=1000, output_tokens=0, cached_tokens=300)

        cost = calc.calculate("model", tokens)

        assert cost == pytest.approx(0.002125, abs=1e-10)

    def test_all_tokens_cached(self):
        """All input tokens cached: effective_input=0, only cached_cost."""
        config = CostConfig(
            rates={
                "model": CostRate(input=0.01, output=0.03, cached=0.5),
            }
        )
        calc = CostCalculator(config)
        tokens = TokenUsage(input_tokens=500, output_tokens=0, cached_tokens=500)

        cost = calc.calculate("model", tokens)

        # effective_input = 0, input_cost = 0
        # cached_cost = (500/1000) * 0.01 * 0.5 = 0.0025
        assert cost == pytest.approx(0.0025, abs=1e-10)

    def test_cached_rate_one_means_no_discount(self):
        """cached=1.0 means cached tokens cost same as regular input."""
        config = CostConfig(
            rates={
                "model": CostRate(input=0.01, output=0.03, cached=1.0),
            }
        )
        calc = CostCalculator(config)
        tokens = TokenUsage(input_tokens=1000, output_tokens=0, cached_tokens=500)

        cost = calc.calculate("model", tokens)

        # effective_input = 500, input_cost = (500/1000)*0.01 = 0.005
        # cached_cost = (500/1000)*0.01*1.0 = 0.005
        # total = 0.01 (same as no caching)
        assert cost == pytest.approx(0.01, abs=1e-10)


class TestCostCalculatorUnknownModel:
    """Unknown model falls back to default rate."""

    def test_unknown_model_uses_default_rate(self):
        """Model not in rates dict uses default CostRate."""
        config = CostConfig(
            rates={
                "known.model": CostRate(input=0.1, output=0.2, cached=1.0),
            },
            default=CostRate(input=0.005, output=0.015, cached=1.0),
        )
        calc = CostCalculator(config)
        tokens = TokenUsage(input_tokens=1000, output_tokens=500)

        cost = calc.calculate("unknown.model", tokens)

        # Uses default: input=0.005, output=0.015
        # input_cost = (1000/1000)*0.005 = 0.005
        # output_cost = (500/1000)*0.015 = 0.0075
        assert cost == pytest.approx(0.0125, abs=1e-10)

    def test_empty_rates_uses_default(self):
        """Empty rates dict always uses default."""
        config = CostConfig(
            rates={},
            default=CostRate(input=0.01, output=0.02, cached=1.0),
        )
        calc = CostCalculator(config)
        tokens = TokenUsage(input_tokens=1000, output_tokens=1000)

        cost = calc.calculate("any.model", tokens)

        # (1000/1000)*0.01 + (1000/1000)*0.02 = 0.03
        assert cost == pytest.approx(0.03, abs=1e-10)


class TestCostCalculatorZeroTokens:
    """Zero tokens edge cases."""

    def test_zero_tokens_returns_zero(self):
        """All tokens zero returns cost 0."""
        config = CostConfig(
            rates={
                "model": CostRate(input=0.01, output=0.02, cached=1.0),
            }
        )
        calc = CostCalculator(config)
        tokens = TokenUsage(input_tokens=0, output_tokens=0, cached_tokens=0)

        cost = calc.calculate("model", tokens)

        assert cost == 0.0

    def test_default_tokens_returns_zero(self):
        """TokenUsage with all defaults (0) returns cost 0."""
        config = CostConfig(
            rates={
                "model": CostRate(input=0.05, output=0.1, cached=1.0),
            }
        )
        calc = CostCalculator(config)
        tokens = TokenUsage()

        cost = calc.calculate("model", tokens)

        assert cost == 0.0

    def test_large_tokens_no_overflow(self):
        """Large token counts calculate correctly without overflow."""
        config = CostConfig(
            rates={
                "model": CostRate(input=0.01, output=0.02, cached=1.0),
            }
        )
        calc = CostCalculator(config)
        tokens = TokenUsage(input_tokens=1_000_000, output_tokens=500_000)

        cost = calc.calculate("model", tokens)

        # (1_000_000/1000)*0.01 + (500_000/1000)*0.02 = 10 + 10 = 20
        assert cost == pytest.approx(20.0, abs=1e-6)


class TestCostCalculatorRounding:
    """Cost rounding behavior."""

    def test_result_rounded_to_10_decimals(self):
        """Cost is rounded to 10 decimal places."""
        config = CostConfig(
            rates={
                "model": CostRate(input=0.00123456789, output=0.00123456789, cached=1.0),
            }
        )
        calc = CostCalculator(config)
        tokens = TokenUsage(input_tokens=1, output_tokens=1)

        cost = calc.calculate("model", tokens)

        # Verify the cost has at most 10 decimal places
        cost_str = str(cost)
        if "." in cost_str:
            decimals = len(cost_str.split(".")[1])
            assert decimals <= 10

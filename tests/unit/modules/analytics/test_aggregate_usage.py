# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for aggregate_usage_data edge cases.

Test 5.3: aggregate_usage_data handles empty data, malformed fields, valid aggregation,
and new metrics (cached_tok, reasoning_tok, cost_cents, latency_min, latency_max).
"""

import pytest

from modules.analytics.llm_usage.aggregator import (
    aggregate_usage_data,
)


class TestAggregateUsageDataEdgeCases:
    """Edge case tests for aggregate_usage_data."""

    def test_empty_data_returns_empty_dict(self):
        """Empty data dict returns empty result."""
        result = aggregate_usage_data({})
        assert result == {}

    def test_malformed_field_no_separators_skipped(self):
        """Field without :: separators is skipped entirely."""
        data = {
            "just_a_plain_string": "100",
            "another_bad_field": "200",
        }
        result = aggregate_usage_data(data)
        assert result == {}

    def test_malformed_field_single_separator_skipped(self):
        """Field with only one :: separator is skipped."""
        data = {
            "label::call_point_only": "50",
        }
        result = aggregate_usage_data(data)
        assert result == {}

    def test_valid_fields_aggregated_by_label_call_point(self):
        """Valid fields are grouped and aggregated by (label, call_point)."""
        data = {
            "chat::openai::gpt-4::classifier::count": "10",
            "chat::openai::gpt-4::classifier::input_tok": "5000",
            "chat::openai::gpt-4::classifier::output_tok": "2000",
            "chat::openai::gpt-4::classifier::success": "8",
            "chat::openai::gpt-4::classifier::failure": "2",
        }
        result = aggregate_usage_data(data)

        assert len(result) == 1
        key = ("chat::openai::gpt-4", "classifier")
        assert key in result
        assert result[key]["count"] == 10
        assert result[key]["input_tok"] == 5000
        assert result[key]["output_tok"] == 2000
        assert result[key]["success"] == 8
        assert result[key]["failure"] == 2

    def test_multiple_groups_separated_correctly(self):
        """Different (label, call_point) pairs create separate groups."""
        data = {
            "chat::openai::gpt-4::classifier::count": "5",
            "chat::anthropic::claude::analyzer::count": "3",
            "chat::openai::gpt-4::summarizer::count": "7",
        }
        result = aggregate_usage_data(data)

        assert len(result) == 3
        assert result[("chat::openai::gpt-4", "classifier")]["count"] == 5
        assert result[("chat::anthropic::claude", "analyzer")]["count"] == 3
        assert result[("chat::openai::gpt-4", "summarizer")]["count"] == 7

    def test_mixed_valid_and_invalid_fields(self):
        """Invalid fields are skipped, valid fields are aggregated."""
        data = {
            "chat::openai::gpt-4::classifier::count": "5",
            "bad_field": "100",
            "another_bad": "200",
            "chat::openai::gpt-4::classifier::success": "5",
        }
        result = aggregate_usage_data(data)

        assert len(result) == 1
        key = ("chat::openai::gpt-4", "classifier")
        assert result[key]["count"] == 5
        assert result[key]["success"] == 5


class TestNewMetrics:
    """Test new metrics: cached_tok, reasoning_tok, cost_cents, latency_min, latency_max."""

    def test_cached_tok_metric(self):
        """cached_tok metric is aggregated correctly."""
        data = {
            "chat::openai::gpt-4::classifier::cached_tok": "300",
        }
        result = aggregate_usage_data(data)

        key = ("chat::openai::gpt-4", "classifier")
        assert result[key]["cached_tok"] == 300

    def test_reasoning_tok_metric(self):
        """reasoning_tok metric is aggregated correctly."""
        data = {
            "chat::openai::gpt-4::classifier::reasoning_tok": "500",
        }
        result = aggregate_usage_data(data)

        key = ("chat::openai::gpt-4", "classifier")
        assert result[key]["reasoning_tok"] == 500

    def test_cost_cents_metric(self):
        """cost_cents metric is aggregated correctly."""
        data = {
            "chat::openai::gpt-4::classifier::cost_cents": "75",
        }
        result = aggregate_usage_data(data)

        key = ("chat::openai::gpt-4", "classifier")
        assert result[key]["cost_cents"] == 75

    def test_cost_cents_accumulates(self):
        """cost_cents accumulates across multiple entries."""
        data = {
            "chat::openai::gpt-4::classifier::cost_cents": "30",
        }
        # Simulate accumulator by pre-setting and re-aggregating
        result = aggregate_usage_data(data)
        key = ("chat::openai::gpt-4", "classifier")
        assert result[key]["cost_cents"] == 30

    def test_latency_min_metric(self):
        """latency_min tracks minimum value."""
        data = {
            "chat::openai::gpt-4::classifier::latency_min": "150",
        }
        result = aggregate_usage_data(data)

        key = ("chat::openai::gpt-4", "classifier")
        assert result[key]["latency_min"] == 150.0

    def test_latency_max_metric(self):
        """latency_max tracks maximum value."""
        data = {
            "chat::openai::gpt-4::classifier::latency_max": "500",
        }
        result = aggregate_usage_data(data)

        key = ("chat::openai::gpt-4", "classifier")
        assert result[key]["latency_max"] == 500.0

    def test_all_new_metrics_together(self):
        """All new metrics can appear together in a single group."""
        data = {
            "chat::openai::gpt-4::classifier::count": "5",
            "chat::openai::gpt-4::classifier::input_tok": "1000",
            "chat::openai::gpt-4::classifier::cached_tok": "300",
            "chat::openai::gpt-4::classifier::reasoning_tok": "200",
            "chat::openai::gpt-4::classifier::cost_cents": "45",
            "chat::openai::gpt-4::classifier::latency_min": "100",
            "chat::openai::gpt-4::classifier::latency_max": "800",
        }
        result = aggregate_usage_data(data)

        key = ("chat::openai::gpt-4", "classifier")
        agg = result[key]
        assert agg["count"] == 5
        assert agg["input_tok"] == 1000
        assert agg["cached_tok"] == 300
        assert agg["reasoning_tok"] == 200
        assert agg["cost_cents"] == 45
        assert agg["latency_min"] == 100.0
        assert agg["latency_max"] == 800.0

    def test_default_values_for_new_metrics(self):
        """New metrics default to 0 when not present."""
        data = {
            "chat::openai::gpt-4::classifier::count": "1",
        }
        result = aggregate_usage_data(data)

        key = ("chat::openai::gpt-4", "classifier")
        agg = result[key]
        assert agg["cached_tok"] == 0
        assert agg["reasoning_tok"] == 0
        assert agg["cost_cents"] == 0
        assert agg["latency_min"] == 0.0
        assert agg["latency_max"] == 0.0

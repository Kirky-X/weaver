# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for core.types.pipeline_state degradation summary.

OCR LOW #197: ``get_degradation_summary`` used to silently map unknown
fields to ``"Unknown reason"``, hiding a desync between
``degraded_fields`` and ``degradation_reasons``. It must now log a warning
so the inconsistency stays observable while keeping the return contract.
"""

from __future__ import annotations

from unittest.mock import patch

from core.types.pipeline_state import get_degradation_summary


class TestGetDegradationSummary:
    """Tests for get_degradation_summary desync warning."""

    def test_in_sync_returns_reasons_without_warning(self) -> None:
        state = {
            "degraded_fields": ["a", "b"],
            "degradation_reasons": {"a": "llm timeout", "b": "parse error"},
        }
        with patch("core.types.pipeline_state.logger") as mock_logger:
            summary = get_degradation_summary(state)

        assert summary == {"a": "llm timeout", "b": "parse error"}
        mock_logger.warning.assert_not_called()

    def test_desync_logs_warning_and_keeps_sentinel(self) -> None:
        """缺少 reason 的字段仍返回 'Unknown reason'，但必须告警。"""
        state = {
            "degraded_fields": ["a", "missing"],
            "degradation_reasons": {"a": "llm timeout"},
        }
        with patch("core.types.pipeline_state.logger") as mock_logger:
            summary = get_degradation_summary(state)

        assert summary == {"a": "llm timeout", "missing": "Unknown reason"}
        mock_logger.warning.assert_called_once()
        _, kwargs = mock_logger.warning.call_args
        assert kwargs["fields"] == ["missing"]

    def test_empty_state_no_warning(self) -> None:
        with patch("core.types.pipeline_state.logger") as mock_logger:
            summary = get_degradation_summary({})

        assert summary == {}
        mock_logger.warning.assert_not_called()

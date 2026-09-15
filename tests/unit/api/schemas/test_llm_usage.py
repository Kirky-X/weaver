# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Regression tests for LLM usage schema success_rate bounds.

``success_rate`` is documented as a 0.0–1.0 ratio. The schema MUST reject
out-of-range values (e.g. 1.5 from a mis-computed ``success/failure`` ratio)
instead of serializing them silently.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.schemas.llm_usage import (
    LLMUsageByCallPoint,
    LLMUsageByModel,
    LLMUsageByProvider,
    LLMUsageSummary,
)


class TestSuccessRateBounds:
    """``success_rate`` MUST stay within [0.0, 1.0] for every usage model."""

    @pytest.mark.parametrize(
        "model_cls,kwargs",
        [
            (
                LLMUsageByProvider,
                {"provider": "p", "call_count": 1, "total_tokens": 10},
            ),
            (
                LLMUsageByModel,
                {
                    "model": "m",
                    "provider": "p",
                    "call_count": 1,
                    "total_tokens": 10,
                },
            ),
            (
                LLMUsageByCallPoint,
                {"call_point": "cp", "call_count": 1, "total_tokens": 10},
            ),
            (
                LLMUsageSummary,
                {
                    "total_calls": 1,
                    "total_input_tokens": 1,
                    "total_output_tokens": 1,
                    "total_tokens": 2,
                    "avg_latency_ms": 1.0,
                },
            ),
        ],
    )
    def test_valid_rate_accepted(self, model_cls, kwargs: dict) -> None:
        """A rate inside [0, 1] builds without error."""
        model = model_cls(success_rate=0.75, **kwargs)
        assert model.success_rate == 0.75

    @pytest.mark.parametrize(
        "model_cls,kwargs",
        [
            (
                LLMUsageByProvider,
                {"provider": "p", "call_count": 1, "total_tokens": 10},
            ),
            (
                LLMUsageByModel,
                {
                    "model": "m",
                    "provider": "p",
                    "call_count": 1,
                    "total_tokens": 10,
                },
            ),
            (
                LLMUsageByCallPoint,
                {"call_point": "cp", "call_count": 1, "total_tokens": 10},
            ),
            (
                LLMUsageSummary,
                {
                    "total_calls": 1,
                    "total_input_tokens": 1,
                    "total_output_tokens": 1,
                    "total_tokens": 2,
                    "avg_latency_ms": 1.0,
                },
            ),
        ],
    )
    def test_rate_above_one_rejected(self, model_cls, kwargs: dict) -> None:
        """A rate > 1.0 (e.g. success/failure ratio) MUST raise."""
        with pytest.raises(ValidationError):
            model_cls(success_rate=1.5, **kwargs)

    @pytest.mark.parametrize(
        "model_cls,kwargs",
        [
            (
                LLMUsageByProvider,
                {"provider": "p", "call_count": 1, "total_tokens": 10},
            ),
            (
                LLMUsageSummary,
                {
                    "total_calls": 1,
                    "total_input_tokens": 1,
                    "total_output_tokens": 1,
                    "total_tokens": 2,
                    "avg_latency_ms": 1.0,
                },
            ),
        ],
    )
    def test_negative_rate_rejected(self, model_cls, kwargs: dict) -> None:
        """A negative rate MUST raise."""
        with pytest.raises(ValidationError):
            model_cls(success_rate=-0.2, **kwargs)

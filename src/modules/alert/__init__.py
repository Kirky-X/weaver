# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Alert module — trend alert evaluation.

This package groups alert-related services:
- trend_evaluator: TrendAlertEvaluator implementing hourly evaluation of
  trend_spike / trend_drop / sentiment_shift rules with 24h payload-hash
  dedup.
"""

from __future__ import annotations

from modules.alert.trend_evaluator import TrendAlertEvaluator

__all__ = ["TrendAlertEvaluator"]

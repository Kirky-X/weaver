# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Trend module — sentiment time-series analysis and trend detection.

This package groups trend-related services:
- models: SentimentTrendResult dataclass (T011) and (later) TrendDetectionResult (T014)
- sentiment: SentimentTrendAnalyzer implementing SentimentTrendProtocol (T012)
- detection: TrendDetector implementing TrendDetectionProtocol (T015, future)
"""

from __future__ import annotations

from modules.trend.models import SentimentTrendResult

__all__ = ["SentimentTrendResult"]

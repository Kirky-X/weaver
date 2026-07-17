# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Trend module — sentiment time-series analysis and trend detection.

This package groups trend-related services:
- models: SentimentTrendResult dataclass (T011) and TrendDetectionResult (T014)
- sentiment: SentimentTrendAnalyzer implementing SentimentTrendProtocol (T012)
- detection: TrendDetector implementing TrendDetectionProtocol (T015)
"""

from __future__ import annotations

from modules.trend.models import SentimentTrendResult, TrendDetectionResult
from modules.trend.sentiment import SentimentTrendAnalyzer

__all__ = ["SentimentTrendAnalyzer", "SentimentTrendResult", "TrendDetectionResult"]

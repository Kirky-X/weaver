# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Trend module — sentiment time-series analysis and trend detection.

This package groups trend-related services:
- models: SentimentTrendResult dataclass and TrendDetectionResult
- sentiment: SentimentTrendAnalyzer implementing SentimentTrendProtocol
- detection: TrendDetector implementing TrendDetectionProtocol
"""

from __future__ import annotations

from modules.trend.detection import TrendDetector
from modules.trend.models import SentimentTrendResult, TrendDetectionResult
from modules.trend.sentiment import SentimentTrendAnalyzer

__all__ = [
    "SentimentTrendAnalyzer",
    "SentimentTrendResult",
    "TrendDetectionResult",
    "TrendDetector",
]

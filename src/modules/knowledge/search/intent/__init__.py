# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Intent-aware search modules - MAGMA-inspired query analysis and routing."""

from .classifier import IntentClassifier
from .router import IntentRouter, RoutingConfig
from .schemas import IntentClassification, QueryIntent, TemporalSignal, TimeAnchor, TimeWindow

__all__ = [
    "IntentClassification",
    "IntentClassifier",
    "IntentRouter",
    "QueryIntent",
    "RoutingConfig",
    "TemporalSignal",
    "TimeAnchor",
    "TimeWindow",
]

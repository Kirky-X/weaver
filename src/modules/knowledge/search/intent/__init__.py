# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Schemas for intent-aware search following MAGMA intent taxonomy."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class QueryIntent(StrEnum):
    """Query intent types - MAGMA intent taxonomy."""

    WHY = "why"  # Causal reasoning - prioritize Causal Graph
    WHEN = "when"  # Time-based query - prioritize Temporal Graph
    ENTITY = "entity"  # Entity-focused query - prioritize Entity Graph
    MULTI_HOP = "multi_hop"  # Multi-hop reasoning - combine graphs
    OPEN = "open"  # Open-domain query - comprehensive search


@dataclass
class TemporalSignal:
    """Detected temporal signal from query."""

    expression: str
    """Original temporal expression (e.g., "last Friday", "yesterday")"""

    anchor_type: str  # "relative" or "absolute"

    resolved_timestamp: datetime | None = None
    """Resolved absolute timestamp if resolvable now"""


@dataclass
class TimeAnchor:
    """Time anchor for temporal resolution."""

    reference_time: datetime
    """Reference time (e.g., query time or current time)"""

    expression: str
    """Original temporal expression"""

    resolved: datetime
    """Resolved absolute timestamp"""


@dataclass
class TimeWindow:
    """Time window for temporal filtering."""

    start: datetime | None = None
    """Start of time window."""

    end: datetime | None = None
    """End of time window."""

    relative_to_query: bool = False
    """Whether this window is relative to query time."""


@dataclass
class IntentClassification:
    """Intent classification result."""

    intent: QueryIntent
    """Detected primary intent."""

    confidence: float = 0.0
    """Classification confidence score [0, 1]."""

    temporal_signals: list[TemporalSignal] | None = None
    """Detected temporal signals for WHEN queries."""

    entity_signals: list[str] | None = None
    """Detected entity names for ENTITY queries."""

    keywords: list[str] | None = None
    """Extracted keywords for search."""

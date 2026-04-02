# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Schemas for temporal inference engine."""

from dataclasses import dataclass
from datetime import datetime


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

    start: datetime | None
    """Start of time window."""

    end: datetime | None
    """End of time window."""

    relative_to_query: bool
    """Whether this window is relative to query time."""

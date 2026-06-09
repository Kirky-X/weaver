# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Briefing module — daily news briefing generation."""

from __future__ import annotations

from modules.briefing.diversity import CategoryDiversity
from modules.briefing.engine import BriefingEngine
from modules.briefing.models import Briefing, BriefingConfig, BriefingItem
from modules.briefing.scorer import BriefingScorer

__all__ = [
    "Briefing",
    "BriefingConfig",
    "BriefingEngine",
    "BriefingItem",
    "BriefingScorer",
    "CategoryDiversity",
]

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Briefing module — daily news briefing generation."""

from __future__ import annotations

from modules.briefing.diversity import CategoryDiversity
from modules.briefing.engine import DailyBriefingEngine
from modules.briefing.generator import BriefingGenerator
from modules.briefing.models import Briefing, BriefingConfig, BriefingItem, BriefingResult
from modules.briefing.scorer import BriefingScorer

__all__ = [
    "Briefing",
    "BriefingConfig",
    "BriefingGenerator",
    "BriefingItem",
    "BriefingResult",
    "BriefingScorer",
    "CategoryDiversity",
    "DailyBriefingEngine",
]

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Briefing module — daily news briefing generation."""

from __future__ import annotations

from modules.briefing.generator import BriefingGenerator
from modules.briefing.models import Briefing, BriefingConfig, BriefingItem, BriefingResult
from modules.briefing.service import BriefingAlreadyExistsError, DailyBriefingService
from modules.briefing.templates import BRIEFING_TEMPLATES, BriefingTemplate, get_template

__all__ = [
    "BRIEFING_TEMPLATES",
    "Briefing",
    "BriefingAlreadyExistsError",
    "BriefingConfig",
    "BriefingGenerator",
    "BriefingItem",
    "BriefingResult",
    "BriefingTemplate",
    "DailyBriefingService",
    "get_template",
]

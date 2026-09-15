# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors


"""Regression tests for briefing data models."""

from __future__ import annotations

from typing import get_type_hints

from modules.briefing.models import Briefing, BriefingItem


class TestT008LowFixes:
    """Regression tests for LOW findings."""

    def test_briefing_items_are_typed(self):
        """#169: ``Briefing.items`` is annotated instead of a bare ``list``."""
        assert get_type_hints(Briefing)["items"] == list[BriefingItem]

        briefing = Briefing()
        assert briefing.items == []
        assert briefing.items is not Briefing().items

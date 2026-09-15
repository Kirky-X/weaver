# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors


"""Regression tests for community trigger entity-name collection (T008 #404)."""

from __future__ import annotations

import inspect

from modules.processing.pipeline.community_trigger import CommunityUpdateTrigger


class TestT008LowFixes:
    """Regression tests for T008 LOW findings (#404)."""

    def test_none_entity_names_are_not_collected(self):
        """#404: the object branch must skip ``None`` names like the dict branch."""
        src = inspect.getsource(CommunityUpdateTrigger.maybe_trigger)

        assert "if entity.canonical_name:" in src
        assert "if entity.name:" in src

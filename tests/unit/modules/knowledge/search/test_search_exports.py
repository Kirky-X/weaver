# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for search module public exports."""


def test_drift_search_engine_importable():
    from modules.knowledge.search import DRIFTSearchEngine

    assert DRIFTSearchEngine is not None


def test_search_mode_has_five_modes():
    from core.constants import SearchMode

    modes = {m.value for m in SearchMode}
    assert "hybrid" in modes
    assert "local" in modes
    assert "global" in modes
    assert "drift" in modes
    assert "latency" in modes

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for search module public exports."""

import pytest


def test_deep_graph_rag_engine_importable():
    from modules.knowledge.search import DeepGraphRAGEngine

    assert DeepGraphRAGEngine is not None


def test_drift_search_engine_importable():
    from modules.knowledge.search import DRIFTSearchEngine

    assert DRIFTSearchEngine is not None


def test_ef_search_manager_uses_core_constants_search_mode():
    from core.constants import SearchMode as CoreSearchMode
    from modules.knowledge.search.ef_search_manager import SearchMode as EfSearchMode

    # ef_search_manager should import from core.constants
    assert EfSearchMode is CoreSearchMode


def test_search_mode_has_five_modes():
    from core.constants import SearchMode

    modes = {m.value for m in SearchMode}
    assert "hybrid" in modes
    assert "local" in modes
    assert "global" in modes
    assert "drift" in modes
    assert "latency" in modes

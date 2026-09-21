# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
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


def test_knowledge_hybrid_engine_comes_from_search_package():
    """#182: the re-export must resolve to the same class as the search package."""
    import modules.knowledge as knowledge_package
    import modules.knowledge.search as search_package

    assert knowledge_package.HybridSearchEngine is search_package.HybridSearchEngine


def test_retrievers_package_exports_bm25_document():
    """#221: BM25Document is part of the retrievers package public API."""
    import modules.knowledge.search.retrievers as retrievers_package
    import modules.knowledge.search.retrievers.bm25_retriever as retriever_module

    assert retrievers_package.BM25Document is retriever_module.BM25Document
    assert "BM25Document" in retrievers_package.__all__

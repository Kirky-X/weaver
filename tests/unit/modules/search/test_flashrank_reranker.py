# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for FlashrankReranker."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.search.rerankers.flashrank_reranker import FlashrankReranker, RerankResult


class TestFlashrankRerankerInit:
    """Tests for FlashrankReranker initialization."""

    @patch("modules.search.rerankers.flashrank_reranker.FlashrankReranker._initialize_ranker")
    def test_init_default_params(self, mock_init: MagicMock) -> None:
        """Test initialization with default parameters."""
        reranker = FlashrankReranker()

        assert reranker._model_name == "tiny"
        assert reranker._enabled is True
        assert reranker._available is False  # Not initialized because mock prevented it
        mock_init.assert_called_once()

    def test_init_custom_params(self, tmp_path: Path) -> None:
        """Test initialization with custom parameters."""
        reranker = FlashrankReranker(
            model_name="small",
            cache_dir=tmp_path,
            enabled=False,
        )

        assert reranker._model_name == "small"
        assert reranker._cache_dir == tmp_path
        assert reranker._enabled is False
        assert reranker.is_available() is False

    def test_init_disabled(self) -> None:
        """Test initialization with reranker disabled."""
        reranker = FlashrankReranker(enabled=False)

        assert reranker._enabled is False
        assert reranker.is_available() is False


class TestFlashrankRerankerRerank:
    """Tests for FlashrankReranker rerank method."""

    @patch("modules.search.rerankers.flashrank_reranker.FlashrankReranker._initialize_ranker")
    def test_rerank_empty_candidates(self, mock_init: MagicMock) -> None:
        """Test reranking empty candidate list."""
        reranker = FlashrankReranker()
        results = reranker.rerank("test query", candidates=[])

        assert results == []

    def test_rerank_unavailable_returns_original(self) -> None:
        """Test that unavailable reranker returns original candidates."""
        reranker = FlashrankReranker(enabled=False)

        candidates = [
            {"id": "1", "content": "First document", "score": 0.9},
            {"id": "2", "content": "Second document", "score": 0.8},
        ]

        results = reranker.rerank("test query", candidates=candidates)

        assert len(results) == 2
        assert results == candidates

    def test_rerank_respects_top_k(self) -> None:
        """Test that rerank respects top_k parameter."""
        reranker = FlashrankReranker(enabled=False)

        candidates = [
            {"id": "1", "content": "First document", "score": 0.9},
            {"id": "2", "content": "Second document", "score": 0.8},
            {"id": "3", "content": "Third document", "score": 0.7},
        ]

        results = reranker.rerank("test query", candidates=candidates, top_k=2)

        assert len(results) == 2

    def test_rerank_candidates_with_different_fields(self) -> None:
        """Test reranking candidates with different content fields."""
        reranker = FlashrankReranker(enabled=False)

        candidates = [
            {"id": "1", "content": "Content from content field"},
            {"id": "2", "text": "Content from text field"},
            {"id": "3", "title": "Content from title field"},
        ]

        results = reranker.rerank("test query", candidates=candidates)

        assert len(results) == 3

    @patch("modules.search.rerankers.flashrank_reranker.FlashrankReranker._initialize_ranker")
    def test_rerank_with_mock_available(self, mock_init: MagicMock) -> None:
        """Test reranking with mocked available reranker."""
        reranker = FlashrankReranker()
        reranker._available = True
        reranker._ranker = MagicMock()

        # Mock the ranker's rerank method
        mock_result = [
            {"id": "1", "text": "First document", "score": 0.95},
            {"id": "2", "text": "Second document", "score": 0.85},
        ]
        reranker._ranker.rerank = MagicMock(return_value=mock_result)

        candidates = [
            {"id": "1", "content": "First document"},
            {"id": "2", "content": "Second document"},
        ]

        # Patch RerankRequest at its source (flashrank module)
        with patch.dict(
            "sys.modules",
            {"flashrank": MagicMock(RerankRequest=MagicMock)},
        ):
            # Import and use the mock
            results = reranker.rerank("test query", candidates=candidates)

        assert len(results) == 2


class TestFlashrankRerankerWithMetadata:
    """Tests for FlashrankReranker rerank_with_metadata method."""

    def test_rerank_with_metadata_unavailable(self) -> None:
        """Test rerank_with_metadata when reranker unavailable."""
        reranker = FlashrankReranker(enabled=False)

        candidates = [
            {"id": "1", "content": "First", "title": "Title 1"},
            {"id": "2", "content": "Second", "title": "Title 2"},
        ]

        results = reranker.rerank_with_metadata("test query", candidates=candidates)

        assert len(results) == 2
        assert all(isinstance(r, RerankResult) for r in results)

    def test_rerank_with_metadata_structure(self) -> None:
        """Test that results have correct structure."""
        reranker = FlashrankReranker(enabled=False)

        candidates = [
            {"id": "doc-1", "content": "Test content", "title": "Test Title", "score": 0.9},
        ]

        results = reranker.rerank_with_metadata("test query", candidates=candidates)

        assert len(results) == 1
        result = results[0]
        assert result.doc_id == "doc-1"
        assert result.title == "Test Title"
        assert result.original_rank == 0
        assert result.new_rank == 0


class TestFlashrankRerankerHelpers:
    """Tests for FlashrankReranker helper methods."""

    @patch("modules.search.rerankers.flashrank_reranker.FlashrankReranker._initialize_ranker")
    def test_is_available(self, mock_init: MagicMock) -> None:
        """Test is_available method."""
        reranker_enabled = FlashrankReranker(enabled=True)
        reranker_disabled = FlashrankReranker(enabled=False)

        # Enabled may or may not be available depending on installation
        assert reranker_disabled.is_available() is False

    @patch("modules.search.rerankers.flashrank_reranker.FlashrankReranker._initialize_ranker")
    def test_get_model_info(self, mock_init: MagicMock) -> None:
        """Test get_model_info method."""
        reranker = FlashrankReranker(model_name="small", enabled=True)

        info = reranker.get_model_info()

        assert info["model_name"] == "small"
        assert info["model_path"] == "flashrank-Small"
        assert "available" in info
        assert "cache_dir" in info
        assert "enabled" in info


class TestFlashrankModels:
    """Tests for model configurations."""

    def test_available_models(self) -> None:
        """Test that expected models are defined."""
        assert "tiny" in FlashrankReranker.MODELS
        assert "small" in FlashrankReranker.MODELS
        assert "medium" in FlashrankReranker.MODELS
        assert "multilingual" in FlashrankReranker.MODELS

    def test_model_paths(self) -> None:
        """Test that model paths are correctly defined."""
        assert FlashrankReranker.MODELS["tiny"] == "flashrank-Tiny"
        assert FlashrankReranker.MODELS["small"] == "flashrank-Small"

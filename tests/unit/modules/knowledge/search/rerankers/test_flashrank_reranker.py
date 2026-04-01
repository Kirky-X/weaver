# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for FlashrankReranker (knowledge module)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.knowledge.search.rerankers.flashrank_reranker import (
    FlashrankReranker,
    RerankResult,
)


class TestFlashrankRerankerInit:
    """Tests for FlashrankReranker initialization."""

    @patch(
        "modules.knowledge.search.rerankers.flashrank_reranker.FlashrankReranker._initialize_ranker"
    )
    def test_init_default_params(self, mock_init: MagicMock) -> None:
        """Test initialization with default parameters."""
        reranker = FlashrankReranker()

        assert reranker._model_name == "tiny"
        assert reranker._enabled is True
        assert reranker._available is False
        mock_init.assert_called_once()

    def test_init_custom_params(self, tmp_path: Path) -> None:
        """Test initialization with custom parameters."""
        reranker = FlashrankReranker(
            model_name="small",
            cache_dir=str(tmp_path),
            enabled=False,
        )

        assert reranker._model_name == "small"
        assert reranker._enabled is False
        assert reranker.is_available() is False

    def test_init_disabled(self) -> None:
        """Test initialization with reranker disabled."""
        reranker = FlashrankReranker(enabled=False)
        assert reranker._enabled is False
        assert reranker.is_available() is False


class TestFlashrankRerankerRerank:
    """Tests for FlashrankReranker rerank method."""

    @patch(
        "modules.knowledge.search.rerankers.flashrank_reranker.FlashrankReranker._initialize_ranker"
    )
    def test_rerank_empty_candidates(self, mock_init: MagicMock) -> None:
        """Test reranking empty candidate list."""
        reranker = FlashrankReranker()
        results = reranker.rerank("test query", candidates=[])
        assert results == []

    def test_rerank_unavailable_returns_original(self) -> None:
        """Unavailable reranker returns original candidates."""
        reranker = FlashrankReranker(enabled=False)
        candidates = [
            {"id": "1", "content": "First", "score": 0.9},
            {"id": "2", "content": "Second", "score": 0.8},
        ]
        results = reranker.rerank("test query", candidates=candidates)
        assert results == candidates

    def test_rerank_respects_top_k(self) -> None:
        """top_k parameter limits results."""
        reranker = FlashrankReranker(enabled=False)
        candidates = [
            {"id": "1", "content": "A", "score": 0.9},
            {"id": "2", "content": "B", "score": 0.8},
            {"id": "3", "content": "C", "score": 0.7},
        ]
        results = reranker.rerank("query", candidates=candidates, top_k=2)
        assert len(results) == 2

    def test_rerank_different_content_fields(self) -> None:
        """Handles candidates with different content fields."""
        reranker = FlashrankReranker(enabled=False)
        candidates = [
            {"id": "1", "content": "From content"},
            {"id": "2", "text": "From text"},
            {"id": "3", "title": "From title"},
        ]
        results = reranker.rerank("query", candidates=candidates)
        assert len(results) == 3


class TestFlashrankRerankerWithMetadata:
    """Tests for rerank_with_metadata."""

    def test_unavailable_returns_rerank_results(self) -> None:
        """Returns RerankResult objects when unavailable."""
        reranker = FlashrankReranker(enabled=False)
        candidates = [
            {"id": "1", "content": "First", "title": "T1"},
            {"id": "2", "content": "Second", "title": "T2"},
        ]
        results = reranker.rerank_with_metadata("query", candidates)
        assert all(isinstance(r, RerankResult) for r in results)
        assert len(results) == 2

    def test_metadata_structure(self) -> None:
        """Results have correct structure."""
        reranker = FlashrankReranker(enabled=False)
        candidates = [{"id": "d1", "content": "Test", "title": "Title", "score": 0.9}]
        results = reranker.rerank_with_metadata("query", candidates)

        assert results[0].doc_id == "d1"
        assert results[0].title == "Title"
        assert results[0].original_rank == 0
        assert results[0].new_rank == 0

    def test_empty_candidates(self) -> None:
        """Empty candidates returns empty list."""
        reranker = FlashrankReranker(enabled=False)
        results = reranker.rerank_with_metadata("query", [])
        assert results == []


class TestFlashrankInitRanker:
    """Tests for _initialize_ranker method."""

    def test_initialize_ranker_import_error(self) -> None:
        """Test _initialize_ranker handles ImportError gracefully."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp/flashrank_test"
        reranker._enabled = True
        reranker._ranker = None
        reranker._available = False

        with patch.dict("sys.modules", {"flashrank": None}):
            reranker._initialize_ranker()

        assert reranker._available is False

    def test_initialize_ranker_generic_exception(self) -> None:
        """Test _initialize_ranker handles generic exceptions."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp/flashrank_test"
        reranker._enabled = True
        reranker._ranker = None
        reranker._available = False

        with patch(
            "modules.knowledge.search.rerankers.flashrank_reranker.FlashrankReranker.MODELS",
            {"tiny": "flashrank-Tiny"},
        ):
            # Simulate Ranker constructor raising
            import builtins

            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "flashrank":
                    # Create a mock module with Ranker that raises
                    mod = MagicMock()
                    mod.Ranker.side_effect = RuntimeError("Model load failed")
                    return mod
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                reranker._initialize_ranker()

        assert reranker._available is False

    def test_initialize_ranker_unknown_model_name(self) -> None:
        """Test _initialize_ranker with unknown model name falls back."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "unknown_model"
        reranker._cache_dir = "/tmp/flashrank_test"
        reranker._enabled = True
        reranker._ranker = None
        reranker._available = False

        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "flashrank":
                mod = MagicMock()
                mod.Ranker.return_value = MagicMock()
                return mod
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            reranker._initialize_ranker()

        assert reranker._available is True


class TestFlashrankRerankAvailable:
    """Tests for rerank when ranker is available."""

    def test_rerank_with_available_ranker(self) -> None:
        """Test rerank with a mocked available ranker."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp"
        reranker._enabled = True
        reranker._available = True

        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": "1", "text": "hello world", "score": 0.95},
            {"id": "2", "text": "goodbye world", "score": 0.85},
        ]
        reranker._ranker = mock_ranker

        candidates = [
            {"id": "1", "content": "hello world"},
            {"id": "2", "content": "goodbye world"},
        ]

        with patch(
            "modules.knowledge.search.rerankers.flashrank_reranker.FlashrankReranker._initialize_ranker"
        ):
            results = reranker.rerank("test query", candidates)

        assert len(results) == 2
        assert results[0]["rerank_score"] == 0.95
        assert results[1]["rerank_score"] == 0.85

    def test_rerank_with_top_k(self) -> None:
        """Test rerank with top_k parameter."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp"
        reranker._enabled = True
        reranker._available = True

        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": "1", "text": "hello", "score": 0.95},
            {"id": "2", "text": "world", "score": 0.85},
            {"id": "3", "text": "test", "score": 0.75},
        ]
        reranker._ranker = mock_ranker

        candidates = [
            {"id": "1", "content": "hello"},
            {"id": "2", "content": "world"},
            {"id": "3", "content": "test"},
        ]

        results = reranker.rerank("test query", candidates, top_k=2)

        assert len(results) == 2

    def test_rerank_handles_exception(self) -> None:
        """Test rerank handles exception and returns original candidates."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp"
        reranker._enabled = True
        reranker._available = True

        mock_ranker = MagicMock()
        mock_ranker.rerank.side_effect = RuntimeError("Rerank failed")
        reranker._ranker = mock_ranker

        candidates = [{"id": "1", "content": "test"}]

        results = reranker.rerank("test query", candidates)

        assert results == candidates

    def test_rerank_handles_exception_with_top_k(self) -> None:
        """Test rerank exception fallback with top_k."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp"
        reranker._enabled = True
        reranker._available = True

        mock_ranker = MagicMock()
        mock_ranker.rerank.side_effect = RuntimeError("Rerank failed")
        reranker._ranker = mock_ranker

        candidates = [
            {"id": "1", "content": "a"},
            {"id": "2", "content": "b"},
        ]

        results = reranker.rerank("test query", candidates, top_k=1)

        assert len(results) == 1

    def test_rerank_candidates_with_text_field(self) -> None:
        """Test rerank handles candidates using 'text' field."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp"
        reranker._enabled = True
        reranker._available = True

        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": "1", "text": "result", "score": 0.9},
        ]
        reranker._ranker = mock_ranker

        # Candidate has 'text' but no 'content'
        candidates = [{"id": "1", "text": "result text"}]

        results = reranker.rerank("test query", candidates)

        assert len(results) == 1

    def test_rerank_candidates_with_title_field(self) -> None:
        """Test rerank handles candidates using 'title' field only."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp"
        reranker._enabled = True
        reranker._available = True

        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": "1", "text": "result", "score": 0.9},
        ]
        reranker._ranker = mock_ranker

        # Candidate only has 'title'
        candidates = [{"id": "1", "title": "Some Title"}]

        results = reranker.rerank("test query", candidates)

        assert len(results) == 1

    def test_rerank_preserves_extra_fields(self) -> None:
        """Test rerank preserves extra candidate fields."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp"
        reranker._enabled = True
        reranker._available = True

        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": "1", "text": "hello", "score": 0.95, "extra_field": "value"},
        ]
        reranker._ranker = mock_ranker

        candidates = [{"id": "1", "content": "hello", "extra_field": "value"}]

        results = reranker.rerank("test query", candidates)

        assert results[0]["extra_field"] == "value"


class TestFlashrankRerankWithMetadataAvailable:
    """Tests for rerank_with_metadata when ranker is available."""

    def test_metadata_with_available_ranker(self) -> None:
        """Test rerank_with_metadata delegates to rerank when available."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp"
        reranker._enabled = True
        reranker._available = True

        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": "1", "text": "hello", "score": 0.95, "title": "Title1"},
        ]
        reranker._ranker = mock_ranker

        candidates = [{"id": "1", "content": "hello", "title": "Title1"}]

        results = reranker.rerank_with_metadata("test query", candidates)

        assert len(results) == 1
        assert isinstance(results[0], RerankResult)
        assert results[0].doc_id == "1"
        assert results[0].score == 0.95

    def test_metadata_with_top_k(self) -> None:
        """Test rerank_with_metadata with top_k."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp"
        reranker._enabled = True
        reranker._available = True

        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": "1", "text": "hello", "score": 0.95},
            {"id": "2", "text": "world", "score": 0.85},
        ]
        reranker._ranker = mock_ranker

        candidates = [
            {"id": "1", "content": "hello"},
            {"id": "2", "content": "world"},
        ]

        results = reranker.rerank_with_metadata("test query", candidates, top_k=1)

        assert len(results) == 1

    def test_metadata_empty_candidates_available(self) -> None:
        """Test rerank_with_metadata with empty candidates when available."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "tiny"
        reranker._cache_dir = "/tmp"
        reranker._enabled = True
        reranker._available = True
        reranker._ranker = MagicMock()

        results = reranker.rerank_with_metadata("test query", [])

        assert results == []

    def test_metadata_with_top_k_unavailable(self) -> None:
        """Test rerank_with_metadata with top_k when unavailable."""
        reranker = FlashrankReranker(enabled=False)
        candidates = [
            {"id": "1", "content": "a", "score": 0.9},
            {"id": "2", "content": "b", "score": 0.8},
        ]

        results = reranker.rerank_with_metadata("query", candidates, top_k=1)

        assert len(results) == 1


class TestFlashrankHelpers:
    """Tests for helper methods."""

    @patch(
        "modules.knowledge.search.rerankers.flashrank_reranker.FlashrankReranker._initialize_ranker"
    )
    def test_get_model_info(self, mock_init: MagicMock) -> None:
        """get_model_info returns expected keys."""
        reranker = FlashrankReranker(model_name="small", enabled=True)
        info = reranker.get_model_info()

        assert info["model_name"] == "small"
        assert info["model_path"] == "flashrank-Small"
        assert "available" in info
        assert "cache_dir" in info
        assert "enabled" in info

    def test_available_models(self) -> None:
        """Expected models are defined."""
        assert "tiny" in FlashrankReranker.MODELS
        assert "small" in FlashrankReranker.MODELS
        assert "medium" in FlashrankReranker.MODELS
        assert "multilingual" in FlashrankReranker.MODELS

    def test_get_model_info_unknown_model(self) -> None:
        """Test get_model_info with unknown model name."""
        reranker = FlashrankReranker.__new__(FlashrankReranker)
        reranker._model_name = "nonexistent"
        reranker._cache_dir = "/tmp"
        reranker._enabled = True
        reranker._available = False

        info = reranker.get_model_info()
        assert info["model_path"] == "unknown"

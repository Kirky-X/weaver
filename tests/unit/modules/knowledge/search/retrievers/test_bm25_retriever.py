# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for BM25Retriever (knowledge module)."""

from __future__ import annotations

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.knowledge.search.retrievers.bm25_retriever import (
    BM25Document,
    BM25Result,
    BM25Retriever,
)


class TestBM25Document:
    """Tests for BM25Document dataclass."""

    def test_creation(self) -> None:
        doc = BM25Document(doc_id="1", title="Test", content="Content")
        assert doc.doc_id == "1"
        assert doc.metadata == {}


class TestBM25Result:
    """Tests for BM25Result dataclass."""

    def test_creation(self) -> None:
        result = BM25Result(doc_id="1", score=0.5, title="Test", content="Content")
        assert result.score == 0.5


class TestBM25RetrieverInit:
    """Tests for initialization."""

    def test_default_params(self) -> None:
        retriever = BM25Retriever()
        assert retriever._language == "zh"
        assert retriever._k1 == 1.5
        assert retriever._b == 0.75
        assert retriever._retriever is None

    def test_custom_params(self) -> None:
        retriever = BM25Retriever(language="en", k1=2.0, b=0.5)
        assert retriever._language == "en"
        assert retriever._k1 == 2.0


class TestBM25RetrieverIndex:
    """Tests for index method."""

    @patch.object(BM25Retriever, "_load_spacy_model")
    def test_index_empty_documents(self, mock_load: MagicMock) -> None:
        """Empty documents does nothing."""
        retriever = BM25Retriever()
        retriever.index([])
        assert retriever._retriever is None

    @patch.object(BM25Retriever, "_tokenize", return_value=["test", "doc"])
    def test_index_documents(self, mock_tokenize: MagicMock) -> None:
        """Indexing documents creates retriever."""
        retriever = BM25Retriever()
        docs = [BM25Document(doc_id="1", title="Test", content="Content")]
        retriever.index(docs)

        assert retriever._retriever is not None
        assert retriever.get_document_count() == 1


class TestBM25RetrieverRetrieve:
    """Tests for retrieve method."""

    def test_retrieve_no_index(self) -> None:
        """No index returns empty."""
        retriever = BM25Retriever()
        assert retriever.retrieve("test") == []

    @patch.object(BM25Retriever, "_tokenize", return_value=["test"])
    def test_retrieve_empty_query(self, mock_tokenize: MagicMock) -> None:
        """Empty query returns empty."""
        retriever = BM25Retriever()
        retriever._retriever = MagicMock()
        assert retriever.retrieve("") == []
        assert retriever.retrieve("  ") == []

    @patch.object(BM25Retriever, "_tokenize", return_value=["test"])
    def test_retrieve_with_results(self, mock_tokenize: MagicMock) -> None:
        """Retrieve returns results."""
        import numpy as np

        retriever = BM25Retriever()
        retriever._documents = [BM25Document(doc_id="1", title="Test", content="Content")]
        retriever._retriever = MagicMock()
        retriever._retriever.get_scores.return_value = np.array([0.5])

        results = retriever.retrieve("test", top_k=10)
        assert len(results) == 1
        assert results[0].doc_id == "1"


class TestBM25RetrieverAddDocuments:
    """Tests for add_documents method."""

    def test_add_empty(self) -> None:
        """Adding empty list does nothing."""
        retriever = BM25Retriever()
        retriever.add_documents([])
        assert retriever._documents == []

    @patch.object(BM25Retriever, "_tokenize", return_value=["test"])
    def test_add_documents(self, mock_tokenize: MagicMock) -> None:
        """Adding documents increases count."""
        retriever = BM25Retriever()
        retriever._documents = [BM25Document(doc_id="1", title="A", content="A")]
        retriever._doc_id_to_idx = {"1": 0}

        new_docs = [BM25Document(doc_id="2", title="B", content="B")]
        with patch.object(BM25Retriever, "index"):
            retriever.add_documents(new_docs)
        assert retriever.get_document_count() == 2


class TestBM25RetrieverClear:
    """Tests for clear method."""

    def test_clear(self) -> None:
        retriever = BM25Retriever()
        retriever._documents = [BM25Document(doc_id="1", title="A", content="A")]
        retriever._retriever = MagicMock()
        retriever.clear()

        assert retriever._retriever is None
        assert retriever._documents == []
        assert retriever._doc_id_to_idx == {}


class TestBM25RetrieverSaveLoad:
    """Tests for save and load."""

    def test_save_no_index(self) -> None:
        """Save without index does nothing."""
        retriever = BM25Retriever()
        retriever.save("/tmp/test_bm25")  # Should not raise

    def test_save_no_path(self) -> None:
        """Save without path raises ValueError."""
        retriever = BM25Retriever()
        retriever._retriever = MagicMock()
        with pytest.raises(ValueError, match="No save path"):
            retriever.save()

    def test_load_no_path(self) -> None:
        """Load without path raises ValueError."""
        retriever = BM25Retriever()
        with pytest.raises(ValueError, match="No load path"):
            retriever.load()


class TestBM25RetrieverTokenize:
    """Tests for _tokenize method."""

    def test_fallback_whitespace_tokenize(self) -> None:
        """Falls back to whitespace tokenization."""
        retriever = BM25Retriever()
        retriever._nlp = None
        with patch.object(retriever, "_load_spacy_model"):
            retriever._nlp = None
            tokens = retriever._tokenize("hello world test")
            assert tokens == ["hello", "world", "test"]

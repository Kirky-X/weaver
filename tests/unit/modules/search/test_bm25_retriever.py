# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for BM25Retriever."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.search.retrievers.bm25_retriever import BM25Document, BM25Result, BM25Retriever


class TestBM25Document:
    """Tests for BM25Document dataclass."""

    def test_bm25_document_creation(self) -> None:
        """Test creating a BM25Document."""
        doc = BM25Document(
            doc_id="test-1",
            title="Test Title",
            content="Test content for document.",
            metadata={"source": "test"},
        )

        assert doc.doc_id == "test-1"
        assert doc.title == "Test Title"
        assert doc.content == "Test content for document."
        assert doc.metadata == {"source": "test"}

    def test_bm25_document_default_metadata(self) -> None:
        """Test BM25Document with default metadata."""
        doc = BM25Document(
            doc_id="test-2",
            title="Title",
            content="Content",
        )

        assert doc.metadata == {}


class TestBM25RetrieverInit:
    """Tests for BM25Retriever initialization."""

    def test_init_default_params(self) -> None:
        """Test initialization with default parameters."""
        retriever = BM25Retriever()

        assert retriever._language == "zh"
        assert retriever._index_dir is None
        assert retriever._k1 == 1.5
        assert retriever._b == 0.75

    def test_init_custom_params(self, tmp_path: Path) -> None:
        """Test initialization with custom parameters."""
        retriever = BM25Retriever(
            language="en",
            index_dir=tmp_path,
            k1=1.2,
            b=0.8,
        )

        assert retriever._language == "en"
        assert retriever._index_dir == tmp_path
        assert retriever._k1 == 1.2
        assert retriever._b == 0.8


class TestBM25RetrieverIndex:
    """Tests for BM25Retriever indexing."""

    def test_index_documents(self) -> None:
        """Test indexing documents."""
        retriever = BM25Retriever()

        documents = [
            BM25Document(
                doc_id="1", title="Python programming", content="Learn Python programming"
            ),
            BM25Document(doc_id="2", title="Java development", content="Java development guide"),
            BM25Document(doc_id="3", title="Python tutorials", content="Advanced Python tutorials"),
        ]

        retriever.index(documents)

        assert retriever.get_document_count() == 3

    def test_index_empty_documents(self) -> None:
        """Test indexing empty document list."""
        retriever = BM25Retriever()

        retriever.index([])

        assert retriever.get_document_count() == 0

    def test_add_documents(self) -> None:
        """Test adding documents to existing index."""
        retriever = BM25Retriever()

        # Initial index
        retriever.index(
            [
                BM25Document(doc_id="1", title="First", content="First document"),
            ]
        )

        # Add more documents
        retriever.add_documents(
            [
                BM25Document(doc_id="2", title="Second", content="Second document"),
                BM25Document(doc_id="3", title="Third", content="Third document"),
            ]
        )

        assert retriever.get_document_count() == 3


class TestBM25RetrieverRetrieve:
    """Tests for BM25Retriever retrieval."""

    def test_retrieve_basic(self) -> None:
        """Test basic retrieval."""
        retriever = BM25Retriever()

        documents = [
            BM25Document(
                doc_id="1", title="Python programming", content="Learn Python programming basics"
            ),
            BM25Document(doc_id="2", title="Java development", content="Java development guide"),
            BM25Document(
                doc_id="3", title="Python advanced", content="Advanced Python programming"
            ),
        ]

        retriever.index(documents)
        results = retriever.retrieve("Python programming", top_k=10)

        # Should find Python-related documents
        assert len(results) >= 2
        assert all(isinstance(r, BM25Result) for r in results)
        assert all(r.score > 0 for r in results)

    def test_retrieve_empty_index(self) -> None:
        """Test retrieval from empty index."""
        retriever = BM25Retriever()

        results = retriever.retrieve("test query", top_k=10)

        assert results == []

    def test_retrieve_top_k(self) -> None:
        """Test retrieval respects top_k."""
        retriever = BM25Retriever()

        documents = [
            BM25Document(doc_id=str(i), title=f"Document {i}", content=f"Content {i} Python")
            for i in range(20)
        ]

        retriever.index(documents)
        results = retriever.retrieve("Python", top_k=5)

        assert len(results) <= 5

    def test_retrieve_result_structure(self) -> None:
        """Test that retrieval results have correct structure."""
        retriever = BM25Retriever()

        documents = [
            BM25Document(
                doc_id="test-1",
                title="Test Title",
                content="Test content with Python",
                metadata={"category": "tech"},
            ),
        ]

        retriever.index(documents)
        results = retriever.retrieve("Python", top_k=1)

        if results:
            result = results[0]
            assert result.doc_id == "test-1"
            assert result.score > 0
            assert result.title == "Test Title"
            assert "Python" in result.content or "content" in result.content.lower()


class TestBM25RetrieverPersistence:
    """Tests for BM25Retriever persistence."""

    def test_save_and_load(self) -> None:
        """Test saving and loading index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            retriever = BM25Retriever(index_dir=tmpdir)

            documents = [
                BM25Document(doc_id="1", title="Test A", content="Content A"),
                BM25Document(doc_id="2", title="Test B", content="Content B"),
            ]

            retriever.index(documents)
            retriever.save()

            # Create new retriever and load
            retriever2 = BM25Retriever(index_dir=tmpdir)
            retriever2.load()

            assert retriever2.get_document_count() == 2

            # Should be able to search
            results = retriever2.retrieve("Test", top_k=10)
            assert len(results) > 0

    def test_clear_index(self) -> None:
        """Test clearing the index."""
        retriever = BM25Retriever()

        documents = [
            BM25Document(doc_id="1", title="Test", content="Content"),
        ]

        retriever.index(documents)
        assert retriever.get_document_count() == 1

        retriever.clear()

        assert retriever.get_document_count() == 0


class TestBM25RetrieverChinese:
    """Tests for Chinese text handling."""

    def test_chinese_indexing(self) -> None:
        """Test indexing Chinese documents."""
        retriever = BM25Retriever(language="zh")

        documents = [
            BM25Document(doc_id="1", title="人工智能发展", content="人工智能技术正在快速发展"),
            BM25Document(doc_id="2", title="机器学习教程", content="机器学习是人工智能的重要分支"),
            BM25Document(doc_id="3", title="编程语言", content="Python是一种流行的编程语言"),
        ]

        retriever.index(documents)

        assert retriever.get_document_count() == 3

    def test_chinese_retrieval(self) -> None:
        """Test retrieving Chinese documents."""
        retriever = BM25Retriever(language="zh")

        documents = [
            BM25Document(doc_id="1", title="人工智能发展", content="人工智能技术正在快速发展"),
            BM25Document(doc_id="2", title="机器学习教程", content="机器学习是人工智能的重要分支"),
            BM25Document(doc_id="3", title="编程语言", content="Python是一种流行的编程语言"),
        ]

        retriever.index(documents)
        results = retriever.retrieve("人工智能", top_k=10)

        # Should find AI-related documents
        assert len(results) >= 1

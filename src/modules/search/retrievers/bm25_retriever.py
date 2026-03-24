# Copyright (c) 2026 KirkyX. All Rights Reserved
"""BM25 retriever for lexical search using bm25s library.

This module provides high-performance BM25 text retrieval with:
- Chinese text tokenization support via spacy
- Index persistence (save/load)
- Incremental updates
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bm25s
import spacy

from core.observability.logging import get_logger

log = get_logger("bm25_retriever")

# Optional stemmer for English text
try:
    import Stemmer  # type: ignore[import-untyped]

    STEMMER_AVAILABLE = True
except ImportError:
    Stemmer = None  # type: ignore[misc,assignment]
    STEMMER_AVAILABLE = False


@dataclass
class BM25Document:
    """Document for BM25 indexing."""

    doc_id: str
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BM25Result:
    """Result from BM25 retrieval."""

    doc_id: str
    score: float
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BM25Retriever:
    """BM25 retriever using bm25s library with Chinese support.

    Features:
    - High-performance BM25 implementation (500x faster than rank-bm25)
    - Chinese tokenization via spacy
    - Index persistence
    - Incremental document updates

    Args:
        language: Language for tokenization (default: "zh" for Chinese).
        index_dir: Directory for storing index files.
        k1: BM25 k1 parameter (term saturation).
        b: BM25 b parameter (document length normalization).
    """

    # Stemmer is not needed for Chinese, only for English
    SUPPORTED_LANGUAGES = {"zh": "zh_core_web_sm", "en": "en_core_web_sm"}

    def __init__(
        self,
        language: str = "zh",
        index_dir: str | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        """Initialize BM25 retriever.

        Args:
            language: Language code ("zh" or "en").
            index_dir: Directory for index persistence.
            k1: BM25 k1 parameter.
            b: BM25 b parameter.
        """
        self._language = language
        self._index_dir = Path(index_dir) if index_dir else None
        self._k1 = k1
        self._b = b

        self._retriever: bm25s.BM25 | None = None
        self._documents: list[BM25Document] = []
        self._doc_id_to_idx: dict[str, int] = {}
        self._nlp: spacy.Language | None = None
        self._stemmer: Stemmer.Stemmer | None = None

        # Initialize stemmer for English
        if language == "en" and STEMMER_AVAILABLE and Stemmer is not None:
            self._stemmer = Stemmer.Stemmer("english")

        log.info(
            "bm25_retriever_initialized",
            language=language,
            k1=k1,
            b=b,
            index_dir=str(index_dir) if index_dir else None,
        )

    def _load_spacy_model(self) -> None:
        """Load spacy model for tokenization."""
        if self._nlp is not None:
            return

        model_name = self.SUPPORTED_LANGUAGES.get(self._language, "zh_core_web_sm")
        try:
            self._nlp = spacy.load(model_name, disable=["ner", "parser", "lemmatizer"])
            log.info("spacy_model_loaded", model=model_name)
        except OSError:
            log.warning("spacy_model_not_found", model=model_name, fallback="simple_tokenizer")
            self._nlp = None

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text using spacy or simple whitespace tokenization.

        Args:
            text: Text to tokenize.

        Returns:
            List of tokens.
        """
        if self._nlp is None:
            self._load_spacy_model()

        if self._nlp is not None:
            doc = self._nlp(text)
            tokens = [
                token.text.lower() for token in doc if not token.is_space and not token.is_punct
            ]
        else:
            # Fallback: simple whitespace tokenization
            tokens = text.lower().split()

        # Apply stemming for English
        if self._stemmer is not None and tokens:
            tokens = self._stemmer.stemWords(tokens)

        return tokens

    def index(self, documents: list[BM25Document]) -> None:
        """Build BM25 index from documents.

        Args:
            documents: List of documents to index.
        """
        if not documents:
            log.warning("bm25_index_empty_documents")
            return

        self._documents = documents
        self._doc_id_to_idx = {doc.doc_id: i for i, doc in enumerate(documents)}

        # Tokenize all documents
        corpus = []
        for doc in documents:
            combined_text = f"{doc.title} {doc.content}"
            tokens = self._tokenize(combined_text)
            corpus.append(tokens)

        # Build BM25 index
        self._retriever = bm25s.BM25(corpus=corpus, k1=self._k1, b=self._b)
        self._retriever.index(corpus)

        log.info(
            "bm25_index_built",
            num_documents=len(documents),
            avg_tokens=sum(len(t) for t in corpus) / len(corpus) if corpus else 0,
        )

    def add_documents(self, documents: list[BM25Document]) -> None:
        """Add new documents to existing index.

        Note: This rebuilds the index with new documents appended.
        For large-scale updates, use index() with full document set.

        Args:
            documents: New documents to add.
        """
        if not documents:
            return

        # Append to existing documents
        start_idx = len(self._documents)
        for doc in documents:
            self._doc_id_to_idx[doc.doc_id] = start_idx
            self._documents.append(doc)
            start_idx += 1

        # Rebuild index
        self.index(self._documents)

        log.info("bm25_documents_added", count=len(documents), total=len(self._documents))

    def retrieve(self, query: str, top_k: int = 10) -> list[BM25Result]:
        """Retrieve top-k documents for a query.

        Args:
            query: Search query.
            top_k: Number of results to return.

        Returns:
            List of BM25Result objects.
        """
        if self._retriever is None:
            log.warning("bm25_retrieve_no_index")
            return []

        # Handle empty query
        if not query or not query.strip():
            log.debug("bm25_retrieve_empty_query")
            return []

        # Tokenize query
        query_tokens = self._tokenize(query)

        # Get scores using get_scores (more reliable than retrieve)
        scores = self._retriever.get_scores(query_tokens)

        # Get top-k indices
        import numpy as np

        top_k_indices = np.argsort(scores)[-top_k:][::-1]

        # Build result objects
        output = []
        for idx in top_k_indices:
            score = float(scores[idx])
            if score > 0 and idx < len(self._documents):
                doc = self._documents[idx]
                output.append(
                    BM25Result(
                        doc_id=doc.doc_id,
                        score=score,
                        title=doc.title,
                        content=(
                            doc.content[:500] + "..." if len(doc.content) > 500 else doc.content
                        ),
                        metadata=doc.metadata,
                    )
                )

        log.debug("bm25_retrieve_complete", query=query[:50], top_k=top_k, results=len(output))
        return output

    def save(self, path: str | None = None) -> None:
        """Save BM25 index to disk.

        Args:
            path: Directory path for saving. Uses index_dir if not specified.
        """
        if self._retriever is None:
            log.warning("bm25_save_no_index")
            return

        save_dir = Path(path) if path else self._index_dir
        if save_dir is None:
            raise ValueError("No save path specified")

        save_dir.mkdir(parents=True, exist_ok=True)

        # Save bm25s index
        self._retriever.save(str(save_dir / "bm25_index"))

        # Save documents and metadata
        with open(save_dir / "documents.pkl", "wb") as f:
            pickle.dump(
                {
                    "documents": self._documents,
                    "doc_id_to_idx": self._doc_id_to_idx,
                    "language": self._language,
                    "k1": self._k1,
                    "b": self._b,
                },
                f,
            )

        log.info("bm25_index_saved", path=str(save_dir))

    def load(self, path: str | None = None) -> None:
        """Load BM25 index from disk.

        Args:
            path: Directory path for loading. Uses index_dir if not specified.
        """
        load_dir = Path(path) if path else self._index_dir
        if load_dir is None:
            raise ValueError("No load path specified")

        # Load bm25s index
        self._retriever = bm25s.BM25.load(str(load_dir / "bm25_index"), load_corpus=True)

        # Load documents and metadata
        with open(load_dir / "documents.pkl", "rb") as f:
            data = pickle.load(f)  # noqa: S301 - trusted index file

        self._documents = data["documents"]
        self._doc_id_to_idx = data["doc_id_to_idx"]
        self._language = data.get("language", "zh")
        self._k1 = data.get("k1", 1.5)
        self._b = data.get("b", 0.75)

        log.info("bm25_index_loaded", path=str(load_dir), num_documents=len(self._documents))

    def get_document_count(self) -> int:
        """Get the number of indexed documents."""
        return len(self._documents)

    def clear(self) -> None:
        """Clear the index."""
        self._retriever = None
        self._documents = []
        self._doc_id_to_idx = {}
        log.info("bm25_index_cleared")

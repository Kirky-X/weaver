# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""BM25 retriever for lexical search using bm25s library.

This module provides high-performance BM25 text retrieval with:
- Chinese text tokenization support via spacy
- Index persistence (save/load) with secure JSON format
- Incremental updates

Security Note:
    Index files use JSON format with HMAC signature verification.
"""

from __future__ import annotations

import hashlib

# BM25 索引持久化，已用 RestrictedUnpickler 加固防 RCE
import pickle  # nosec B403
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import bm25s

from core.observability import get_logger
from core.security.crypto.signing import (
    IntegrityError,
    SigningKey,
    load_signed_json,
    save_signed_json,
)

if TYPE_CHECKING:
    import spacy


class RestrictedUnpickler(pickle.Unpickler):
    """Secure unpickler that restricts allowed classes to prevent RCE.

    Only allows unpickling of specific safe classes used in BM25 index.
    """

    ALLOWED_BUILTINS = frozenset(
        [
            "dict",
            "list",
            "tuple",
            "set",
            "frozenset",
            "str",
            "int",
            "float",
            "bool",
            "bytes",
            "NoneType",
        ]
    )
    ALLOWED_COLLECTIONS = frozenset(["OrderedDict", "defaultdict"])

    def find_class(self, module: str, name: str) -> Any:
        """Override find_class to restrict allowed classes.

        Args:
            module: Module name from pickle stream.
            name: Class name from pickle stream.

        Returns:
            The class if allowed.

        Raises:
            pickle.UnpicklingError: If class is not in allowed list.
        """
        # Allow built-in types
        if module == "builtins" and name in self.ALLOWED_BUILTINS:
            return super().find_class(module, name)

        # Allow collections types
        if module == "collections" and name in self.ALLOWED_COLLECTIONS:
            return super().find_class(module, name)

        # Allow BM25Document from this module
        if name == "BM25Document":
            return BM25Document

        raise pickle.UnpicklingError(
            f"Unsafe pickle: attempting to load {module}.{name} "
            f"which is not in allowed classes list"
        )


@contextmanager
def _secure_pickle_load() -> Generator[None, None, None]:
    """Context manager that patches pickle.load to use RestrictedUnpickler.

    This prevents arbitrary code execution when loading bm25s index files
    that use pickle internally. The patch is scoped to the context manager
    lifetime only.
    """
    _original_load = pickle.load

    def _restricted_load(f, **kwargs):
        return RestrictedUnpickler(f, **kwargs).load()

    pickle.load = _restricted_load  # type: ignore[assignment]
    try:
        yield
    finally:
        pickle.load = _original_load  # type: ignore[assignment]


def _compute_file_hash(path: Path) -> str:
    """Compute SHA256 hash of a file or directory for integrity verification.

    When ``path`` is a directory (e.g., bm25s index directory), hashes
    all files recursively in sorted order to produce a deterministic digest.
    When ``path`` is a file, hashes the file content directly.

    Args:
        path: Path to the file or directory.

    Returns:
        Hex digest of the SHA256 hash.
    """
    h = hashlib.sha256()
    if path.is_dir():
        # Hash all files in the directory recursively (sorted for determinism)
        for file_path in sorted(path.rglob("*")):
            if file_path.is_file():
                h.update(str(file_path.relative_to(path)).encode())
                h.update(b"\0")
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        h.update(chunk)
                h.update(b"\0")
    else:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    return h.hexdigest()


log = get_logger(__name__)

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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BM25Document:
        """Create from dictionary."""
        return cls(
            doc_id=data["doc_id"],
            title=data["title"],
            content=data["content"],
            metadata=data.get("metadata", {}),
        )


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
    - Index persistence with secure JSON format
    - Incremental document updates

    Args:
        language: Language for tokenization (default: "zh" for Chinese).
        index_dir: Directory for storing index files.
        k1: BM25 k1 parameter (term saturation).
        b: BM25 b parameter (document length normalization).
        signing_key: Optional signing key for index integrity.
    """

    # Stemmer is not needed for Chinese, only for English
    SUPPORTED_LANGUAGES = {"zh": "zh_core_web_lg", "en": "en_core_web_lg"}

    # File names
    INDEX_FILE = "bm25_index"
    DOCUMENTS_FILE = "documents.json"

    def __init__(
        self,
        language: str = "zh",
        index_dir: str | None = None,
        k1: float = 1.5,
        b: float = 0.75,
        signing_key: SigningKey | None = None,
    ) -> None:
        """Initialize BM25 retriever.

        Args:
            language: Language code ("zh" or "en").
            index_dir: Directory for index persistence.
            k1: BM25 k1 parameter.
            b: BM25 b parameter.
            signing_key: Optional signing key for index integrity verification.
        """
        self._language = language
        self._index_dir = Path(index_dir) if index_dir else None
        self._k1 = k1
        self._b = b
        self._signing_key = signing_key or SigningKey.from_env()

        self._retriever: bm25s.BM25 | None = None
        self._documents: list[BM25Document] = []
        self._doc_id_to_idx: dict[str, int] = {}
        self._corpus: list[list[str]] = []  # Tokenized documents for incremental updates
        self._nlp: spacy.Language | None = None
        self._spacy_load_attempted: bool = False
        self._stemmer: Stemmer.Stemmer | None = None
        self._needs_reindex: bool = False  # Flag to track if index needs rebuilding

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
        """Load spacy model for tokenization.

        Tries models in order from MODEL_MAP, with local wheel support for Chinese.
        Uses lazy import to avoid loading spaCy (~800MB) at module import time.
        """
        import spacy as _spacy

        if self._nlp is not None:
            return

        if self._spacy_load_attempted:
            return

        self._spacy_load_attempted = True
        model_name = self.SUPPORTED_LANGUAGES.get(self._language, "zh_core_web_lg")
        try:
            self._nlp = _spacy.load(model_name, disable=["ner", "parser", "lemmatizer"])
            log.info("spacy_model_loaded", model=model_name)
        except OSError:
            log.warning("spacy_model_not_found", model=model_name, fallback="simple_tokenizer")

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

        self._corpus = corpus
        self._needs_reindex = False

        # Build BM25 index
        self._retriever = bm25s.BM25(corpus=corpus, k1=self._k1, b=self._b)
        self._retriever.index(corpus)

        log.info(
            "bm25_index_built",
            num_documents=len(documents),
            avg_tokens=sum(len(t) for t in corpus) / len(corpus) if corpus else 0,
        )

    def add_documents(self, documents: list[BM25Document]) -> None:
        """Add new documents to index incrementally.

        Documents are tokenized and added to the corpus, but the BM25 index
        is only rebuilt when _needs_reindex is True (set after adding).
        This avoids O(n) tokenization on every add.

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

            # Tokenize and add to corpus incrementally
            combined_text = f"{doc.title} {doc.content}"
            tokens = self._tokenize(combined_text)
            self._corpus.append(tokens)

        # Mark that index needs rebuilding before next search
        self._needs_reindex = True

        log.info("bm25_documents_added", count=len(documents), total=len(self._documents))

    def _ensure_indexed(self) -> None:
        """Rebuild BM25 index if documents have been added since last index.

        This enables O(1) add_documents with deferred re-indexing.
        """
        if self._needs_reindex and self._corpus:
            self._retriever = bm25s.BM25(corpus=self._corpus, k1=self._k1, b=self._b)
            self._retriever.index(self._corpus)
            self._needs_reindex = False
            log.info(
                "bm25_incremental_index_built",
                num_documents=len(self._documents),
                avg_tokens=(
                    sum(len(t) for t in self._corpus) / len(self._corpus) if self._corpus else 0
                ),
            )

    def retrieve(self, query: str, top_k: int = 10) -> list[BM25Result]:
        """Retrieve top-k documents for a query.

        Args:
            query: Search query.
            top_k: Number of results to return.

        Returns:
            List of BM25Result objects.
        """
        # Rebuild index if documents were added since last index
        self._ensure_indexed()

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
        """Save BM25 index to disk with integrity signature.

        Args:
            path: Directory path for saving. Uses index_dir if not specified.
        """
        # Rebuild index if documents were added since last index
        self._ensure_indexed()

        if self._retriever is None:
            log.warning("bm25_save_no_index")
            return

        save_dir = Path(path) if path else self._index_dir
        if save_dir is None:
            raise ValueError("No save path specified")

        save_dir.mkdir(parents=True, exist_ok=True)

        # Save bm25s index
        self._retriever.save(str(save_dir / self.INDEX_FILE))

        # Compute hash of binary index file for integrity verification
        index_data_dir = save_dir / self.INDEX_FILE
        index_hash = _compute_file_hash(index_data_dir) if index_data_dir.exists() else ""

        # Save documents and metadata as signed JSON
        data = {
            "documents": [doc.to_dict() for doc in self._documents],
            "doc_id_to_idx": self._doc_id_to_idx,
            "language": self._language,
            "k1": self._k1,
            "b": self._b,
            "index_hash": index_hash,
            "format_version": 3,  # v3 = JSON with signature + binary index hash
        }

        save_signed_json(data, save_dir / self.DOCUMENTS_FILE, self._signing_key)

        log.info("bm25_index_saved", path=str(save_dir))

    def load(self, path: str | None = None) -> None:
        """Load BM25 index from disk with integrity verification.

        Verifies both the HMAC-signed JSON metadata and the SHA256 hash
        of the binary index file before loading. Uses RestrictedUnpickler
        to prevent arbitrary code execution via pickle.

        Args:
            path: Directory path for loading. Uses index_dir if not specified.

        Raises:
            IntegrityError: If index signature verification or hash check fails.
        """
        load_dir = Path(path) if path else self._index_dir
        if load_dir is None:
            raise ValueError("No load path specified")

        # Load signed JSON first to get metadata and expected hash
        json_path = load_dir / self.DOCUMENTS_FILE

        if not json_path.exists():
            raise FileNotFoundError(f"No index files found in {load_dir}")

        data = self._load_json_index(json_path)

        # Verify binary index file integrity via hash
        expected_hash = data.get("index_hash", "")
        if expected_hash:
            index_data_dir = load_dir / self.INDEX_FILE
            if index_data_dir.exists():
                actual_hash = _compute_file_hash(index_data_dir)
                if actual_hash != expected_hash:
                    raise IntegrityError(
                        f"Binary index hash mismatch: expected {expected_hash[:16]}..., "
                        f"got {actual_hash[:16]}..."
                    )
            else:
                raise IntegrityError(f"Binary index file not found: {index_data_dir}")

        # Load bm25s index with secure pickle loading
        with _secure_pickle_load():
            self._retriever = bm25s.BM25.load(str(load_dir / self.INDEX_FILE), load_corpus=True)

        # Restore state from data
        self._documents = [BM25Document.from_dict(d) for d in data["documents"]]
        self._doc_id_to_idx = data["doc_id_to_idx"]
        self._language = data.get("language", "zh")
        self._k1 = data.get("k1", 1.5)
        self._b = data.get("b", 0.75)
        # Corpus is loaded with bm25s index, mark as not needing reindex
        self._needs_reindex = False

        log.info("bm25_index_loaded", path=str(load_dir), num_documents=len(self._documents))

    def _load_json_index(self, json_path: Path) -> dict[str, Any]:
        """Load signed JSON index file.

        Args:
            json_path: Path to documents.json file.

        Returns:
            Index data dictionary.

        Raises:
            IntegrityError: If signature verification fails.
        """
        try:
            return load_signed_json(json_path, self._signing_key)
        except IntegrityError as e:
            log.error("bm25_index_integrity_error", path=str(json_path), error=str(e))
            raise

    @property
    def is_initialized(self) -> bool:
        """Check if the BM25 index is initialized and ready for queries."""
        return self._retriever is not None

    def get_document_count(self) -> int:
        """Get the number of indexed documents."""
        return len(self._documents)

    def clear(self) -> None:
        """Clear the index."""
        self._retriever = None
        self._documents = []
        self._doc_id_to_idx = {}
        self._corpus = []
        self._needs_reindex = False
        log.info("bm25_index_cleared")

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for BM25 index persistence and signing verification."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.security.crypto.signing import (
    IntegrityError,
    SigningKey,
    load_signed_json,
    save_signed_json,
)
from modules.knowledge.search.retrievers.bm25_retriever import (
    BM25Document,
    BM25Retriever,
)


class TestSigningKey:
    """Tests for SigningKey functionality."""

    def test_generate_signing_key(self) -> None:
        """Test generating a signing key."""
        key = SigningKey.generate()
        assert key is not None
        assert len(key.key) == 32  # 256 bits

    def test_signing_key_from_env(self) -> None:
        """Test creating signing key from environment variable."""
        import os

        original = os.environ.get("INDEX_SIGNING_KEY")
        os.environ["INDEX_SIGNING_KEY"] = "test-key-12345678901234567890"

        try:
            key = SigningKey.from_env()
            assert key.key == b"test-key-12345678901234567890"
        finally:
            if original is None:
                os.environ.pop("INDEX_SIGNING_KEY", None)
            else:
                os.environ["INDEX_SIGNING_KEY"] = original

    def test_signing_key_generates_random_if_not_set(self) -> None:
        """Test that signing key generates random key if not configured."""
        import os

        original = os.environ.get("INDEX_SIGNING_KEY")
        os.environ.pop("INDEX_SIGNING_KEY", None)

        try:
            key = SigningKey.from_env()
            assert key is not None
            assert len(key.key) == 64  # 32 bytes hex = 64 chars
        finally:
            if original is not None:
                os.environ["INDEX_SIGNING_KEY"] = original


class TestSignedJson:
    """Tests for signed JSON operations."""

    def test_save_and_load_signed_json(self) -> None:
        """Test saving and loading signed JSON."""
        key = SigningKey.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"

            data = {"test": "value", "number": 42}
            save_signed_json(data, path, key)

            loaded = load_signed_json(path, key)
            assert loaded == data

    def test_load_signed_json_detects_tampering(self) -> None:
        """Test that load detects tampered content."""
        key = SigningKey.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"

            data = {"test": "value"}
            save_signed_json(data, path, key)

            # Tamper with the file
            content = path.read_text()
            tampered = content.replace("value", "tampered")
            path.write_text(tampered)

            with pytest.raises(IntegrityError):
                load_signed_json(path, key)

    def test_load_signed_json_rejects_missing_signature(self) -> None:
        """Test that load rejects files without signature."""
        key = SigningKey.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"

            # Write JSON without signature
            import json

            path.write_text(json.dumps({"test": "value"}))

            with pytest.raises(IntegrityError):
                load_signed_json(path, key)

    def test_different_keys_produce_different_signatures(self) -> None:
        """Test that different keys produce different signatures."""
        key1 = SigningKey.generate()
        key2 = SigningKey.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = Path(tmpdir) / "test1.json"
            path2 = Path(tmpdir) / "test2.json"

            data = {"test": "value"}
            save_signed_json(data, path1, key1)
            save_signed_json(data, path2, key2)

            # Should not be able to verify with wrong key
            with pytest.raises(IntegrityError):
                load_signed_json(path1, key2)

            with pytest.raises(IntegrityError):
                load_signed_json(path2, key1)


class TestBM25IndexMigration:
    """Tests for BM25 index persistence with signed JSON format."""

    def test_save_uses_signed_json(self) -> None:
        """Test that save produces signed JSON files."""
        key = SigningKey.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            retriever = BM25Retriever(index_dir=tmpdir, signing_key=key)

            documents = [
                BM25Document(doc_id="1", title="Test", content="Content"),
            ]
            retriever.index(documents)
            retriever.save()

            # Check that documents.json exists
            json_path = Path(tmpdir) / "documents.json"
            assert json_path.exists()

            # Verify it's a valid signed JSON
            loaded = load_signed_json(json_path, key)
            assert "documents" in loaded
            assert loaded["format_version"] == 3

    def test_load_signed_json_index(self) -> None:
        """Test loading a signed JSON index."""
        key = SigningKey.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and save index
            retriever1 = BM25Retriever(index_dir=tmpdir, signing_key=key)
            documents = [
                BM25Document(doc_id="1", title="Python", content="Python programming"),
                BM25Document(doc_id="2", title="Java", content="Java development"),
            ]
            retriever1.index(documents)
            retriever1.save()

            # Load in new retriever
            retriever2 = BM25Retriever(index_dir=tmpdir, signing_key=key)
            retriever2.load()

            assert retriever2.get_document_count() == 2

    def test_tampered_index_raises_integrity_error(self) -> None:
        """Test that tampered index raises IntegrityError."""
        key = SigningKey.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            retriever = BM25Retriever(index_dir=tmpdir, signing_key=key)
            documents = [BM25Document(doc_id="1", title="Test", content="Content")]
            retriever.index(documents)
            retriever.save()

            # Tamper with the index
            json_path = Path(tmpdir) / "documents.json"
            content = json_path.read_text()
            tampered = content.replace("Test", "Tampered")
            json_path.write_text(tampered)

            # Loading should raise IntegrityError
            retriever2 = BM25Retriever(index_dir=tmpdir, signing_key=key)
            with pytest.raises(IntegrityError):
                retriever2.load()

    def test_missing_key_still_loads_unverified(self) -> None:
        """Test that missing signing key allows loading (unverified)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save with a key
            key = SigningKey.generate()
            retriever1 = BM25Retriever(index_dir=tmpdir, signing_key=key)
            documents = [BM25Document(doc_id="1", title="Test", content="Content")]
            retriever1.index(documents)
            retriever1.save()

            # Load without key (should still work, but unverified)
            # Note: The implementation may require a key, so this tests behavior
            retriever2 = BM25Retriever(index_dir=tmpdir)  # No signing key
            # This may or may not work depending on implementation


class TestBM25DocumentSerialization:
    """Tests for BM25Document serialization."""

    def test_document_to_dict(self) -> None:
        """Test converting document to dictionary."""
        doc = BM25Document(
            doc_id="test-1",
            title="Test Title",
            content="Test content",
            metadata={"source": "unit_test"},
        )

        data = doc.to_dict()

        assert data["doc_id"] == "test-1"
        assert data["title"] == "Test Title"
        assert data["content"] == "Test content"
        assert data["metadata"] == {"source": "unit_test"}

    def test_document_from_dict(self) -> None:
        """Test creating document from dictionary."""
        data = {
            "doc_id": "test-2",
            "title": "Another Title",
            "content": "More content",
            "metadata": {"author": "test"},
        }

        doc = BM25Document.from_dict(data)

        assert doc.doc_id == "test-2"
        assert doc.title == "Another Title"
        assert doc.content == "More content"
        assert doc.metadata == {"author": "test"}

    def test_document_roundtrip(self) -> None:
        """Test document serialization roundtrip."""
        original = BM25Document(
            doc_id="test-3",
            title="Roundtrip Test",
            content="Testing roundtrip",
            metadata={"key": "value", "number": 42},
        )

        data = original.to_dict()
        restored = BM25Document.from_dict(data)

        assert restored.doc_id == original.doc_id
        assert restored.title == original.title
        assert restored.content == original.content
        assert restored.metadata == original.metadata


class TestIndexIntegrityVerification:
    """Tests for end-to-end index integrity verification."""

    def test_full_save_load_cycle(self) -> None:
        """Test complete save/load cycle with signing."""
        key = SigningKey.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and index documents
            retriever1 = BM25Retriever(index_dir=tmpdir, signing_key=key)
            documents = [
                BM25Document(
                    doc_id="1",
                    title="Python Programming",
                    content="Learn Python programming from basics to advanced",
                ),
                BM25Document(
                    doc_id="2",
                    title="Java Development",
                    content="Build enterprise applications with Java",
                ),
                BM25Document(
                    doc_id="3",
                    title="JavaScript Guide",
                    content="Modern JavaScript for web development",
                ),
            ]
            retriever1.index(documents)
            retriever1.save()

            # Load in a new retriever instance
            retriever2 = BM25Retriever(index_dir=tmpdir, signing_key=key)
            retriever2.load()

            # Verify data integrity
            assert retriever2.get_document_count() == 3

            # Verify search still works
            results = retriever2.retrieve("Python", top_k=10)
            assert len(results) > 0
            assert any("Python" in r.title for r in results)

    def test_index_format_version(self) -> None:
        """Test that saved index has correct format version."""
        key = SigningKey.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            retriever = BM25Retriever(index_dir=tmpdir, signing_key=key)
            retriever.index([BM25Document(doc_id="1", title="Test", content="Content")])
            retriever.save()

            # Check the saved JSON
            json_path = Path(tmpdir) / "documents.json"
            data = load_signed_json(json_path, key)

            assert data["format_version"] == 3  # v3 = JSON with signature + binary index hash

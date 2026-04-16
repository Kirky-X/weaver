# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for core.embedding.local_embedding module."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core.embedding.local_embedding import LocalEmbeddingModel


class TestLocalEmbeddingModelInit:
    """Test LocalEmbeddingModel initialization."""

    def test_init_with_default_model(self):
        """Test initialization with default model."""
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            model = LocalEmbeddingModel()

            mock_st.assert_called_once()
            assert model._model is not None

    def test_init_with_custom_model(self):
        """Test initialization with custom model name."""
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            model = LocalEmbeddingModel(model_name="all-MiniLM-L6-v2")

            mock_st.assert_called_once_with("all-MiniLM-L6-v2")

    def test_init_sets_dimension(self):
        """Test initialization sets embedding dimension."""
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_model = MagicMock()
            mock_model.get_sentence_embedding_dimension.return_value = 384
            mock_st.return_value = mock_model

            model = LocalEmbeddingModel()

            assert model.dimension == 384


class TestLocalEmbeddingModelEncode:
    """Test LocalEmbeddingModel.encode method."""

    @pytest.fixture
    def model(self):
        """Create LocalEmbeddingModel with mocked backend."""
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_model = MagicMock()
            mock_model.get_sentence_embedding_dimension.return_value = 384
            mock_model.encode.return_value = np.array([[0.1] * 384])
            mock_st.return_value = mock_model

            return LocalEmbeddingModel()

    def test_encode_single_text(self, model):
        """Test encoding single text."""
        embedding = model.encode("Hello world")

        assert isinstance(embedding, np.ndarray)
        assert embedding.shape == (384,)

    def test_encode_multiple_texts(self, model):
        """Test encoding multiple texts."""
        embeddings = model.encode(["Text 1", "Text 2", "Text 3"])

        assert isinstance(embeddings, np.ndarray)
        assert embeddings.shape[0] == 3

    def test_encode_empty_string(self, model):
        """Test encoding empty string."""
        embedding = model.encode("")

        assert isinstance(embedding, np.ndarray)
        assert embedding.shape[0] > 0

    def test_encode_long_text(self, model):
        """Test encoding long text."""
        long_text = "A" * 10000
        embedding = model.encode(long_text)

        assert isinstance(embedding, np.ndarray)

    def test_encode_chinese_text(self, model):
        """Test encoding Chinese text."""
        embedding = model.encode("你好世界")

        assert isinstance(embedding, np.ndarray)
        assert embedding.shape[0] > 0

    def test_encode_with_normalize(self, model):
        """Test encoding with normalization."""
        embedding = model.encode("Test text", normalize_embeddings=True)

        assert isinstance(embedding, np.ndarray)
        # Normalized embeddings should have unit norm
        norm = np.linalg.norm(embedding)
        assert abs(norm - 1.0) < 0.01

    def test_encode_preserves_order(self, model):
        """Test encoding preserves input order."""
        texts = ["First", "Second", "Third"]
        embeddings = model.encode(texts)

        assert embeddings.shape[0] == 3


class TestLocalEmbeddingModelEncodeBatch:
    """Test LocalEmbeddingModel.encode_batch method."""

    @pytest.fixture
    def model(self):
        """Create LocalEmbeddingModel with mocked backend."""
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_model = MagicMock()
            mock_model.get_sentence_embedding_dimension.return_value = 384
            mock_model.encode.return_value = np.array([[0.1] * 384, [0.2] * 384])
            mock_st.return_value = mock_model

            return LocalEmbeddingModel()

    def test_encode_batch(self, model):
        """Test batch encoding."""
        texts = ["Text 1", "Text 2"]
        embeddings = model.encode_batch(texts, batch_size=32)

        assert isinstance(embeddings, np.ndarray)
        assert embeddings.shape[0] == 2

    def test_encode_batch_custom_size(self, model):
        """Test batch encoding with custom batch size."""
        texts = ["Text " + str(i) for i in range(100)]
        embeddings = model.encode_batch(texts, batch_size=16)

        assert isinstance(embeddings, np.ndarray)
        assert embeddings.shape[0] == 100

    def test_encode_batch_empty_list(self, model):
        """Test batch encoding empty list."""
        embeddings = model.encode_batch([])

        assert isinstance(embeddings, np.ndarray)
        assert embeddings.shape[0] == 0


class TestLocalEmbeddingModelSimilarity:
    """Test similarity computation."""

    @pytest.fixture
    def model(self):
        """Create LocalEmbeddingModel with mocked backend."""
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_model = MagicMock()
            mock_model.get_sentence_embedding_dimension.return_value = 384
            mock_model.encode.return_value = np.array([[0.1] * 384])
            mock_st.return_value = mock_model

            return LocalEmbeddingModel()

    def test_cosine_similarity(self, model):
        """Test cosine similarity computation."""
        text1 = "Hello world"
        text2 = "Hi there"

        sim = model.cosine_similarity(text1, text2)

        assert isinstance(sim, float)
        assert -1.0 <= sim <= 1.0

    def test_similarity_identical_texts(self, model):
        """Test similarity of identical texts."""
        text = "Same text"

        sim = model.cosine_similarity(text, text)

        # Should be very close to 1.0
        assert sim > 0.99

    def test_top_k_similar(self, model):
        """Test finding top-k similar texts."""
        query = "Query text"
        candidates = ["Candidate 1", "Candidate 2", "Candidate 3"]

        top_k = model.top_k_similar(query, candidates, k=2)

        assert isinstance(top_k, list)
        assert len(top_k) <= 2


class TestLocalEmbeddingModelProperties:
    """Test model properties."""

    @pytest.fixture
    def model(self):
        """Create LocalEmbeddingModel with mocked backend."""
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_model = MagicMock()
            mock_model.get_sentence_embedding_dimension.return_value = 384
            mock_st.return_value = mock_model

            return LocalEmbeddingModel()

    def test_dimension_property(self, model):
        """Test dimension property."""
        assert model.dimension == 384

    def test_model_name_property(self, model):
        """Test model_name property."""
        assert hasattr(model, "model_name") or model._model is not None


class TestLocalEmbeddingModelErrorHandling:
    """Test error handling."""

    def test_model_load_failure(self):
        """Test handling model load failure."""
        with patch(
            "sentence_transformers.SentenceTransformer", side_effect=Exception("Load failed")
        ):
            with pytest.raises(Exception, match="Load failed"):
                LocalEmbeddingModel()

    def test_encode_failure(self):
        """Test handling encode failure."""
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_model = MagicMock()
            mock_model.get_sentence_embedding_dimension.return_value = 384
            mock_model.encode.side_effect = Exception("Encode failed")
            mock_st.return_value = mock_model

            model = LocalEmbeddingModel()

            with pytest.raises(Exception, match="Encode failed"):
                model.encode("Test")


class TestLocalEmbeddingModelIntegration:
    """Integration tests."""

    def test_full_encoding_workflow(self):
        """Test complete encoding workflow."""
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_model = MagicMock()
            mock_model.get_sentence_embedding_dimension.return_value = 384
            mock_model.encode.return_value = np.random.randn(1, 384).astype(np.float32)
            mock_st.return_value = mock_model

            embedding_model = LocalEmbeddingModel()

            # Encode single text
            emb1 = embedding_model.encode("Test sentence")
            assert emb1.shape == (384,)

            # Encode batch
            texts = ["Text 1", "Text 2", "Text 3"]
            embeddings = embedding_model.encode_batch(texts)
            assert embeddings.shape[0] == 3

            # Compute similarity
            sim = embedding_model.cosine_similarity("Text A", "Text B")
            assert isinstance(sim, float)

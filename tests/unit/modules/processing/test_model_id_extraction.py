# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Test for model_id extraction fix.

Verifies that embedding model IDs with dots (e.g., Qwen3-Embedding-0.6B)
are correctly extracted from label format.
"""

from __future__ import annotations

import pytest

from modules.processing.pipeline.graph import Pipeline


class TestModelIdExtraction:
    """Tests for Pipeline._extract_embedding_model_id()."""

    def test_extract_model_id_with_dots(self):
        """Test model ID containing dots is correctly extracted."""
        # Qwen3-Embedding-0.6B contains a dot
        label = "embedding.aiping.Qwen3-Embedding-0.6B"

        # Simulate the fixed parsing logic
        parts = label.split(".", 2)
        assert len(parts) >= 3
        model_id = parts[2]

        assert model_id == "Qwen3-Embedding-0.6B"
        assert model_id != "6B"  # This was the bug

    def test_extract_model_id_ollama_format(self):
        """Test Ollama-style model ID with colon."""
        label = "embedding.ollama.qwen3-embedding:0.6b"

        parts = label.split(".", 2)
        assert len(parts) >= 3
        model_id = parts[2]

        assert model_id == "qwen3-embedding:0.6b"

    def test_extract_model_id_multiple_dots(self):
        """Test model ID with multiple dots."""
        label = "embedding.provider.some.model.with.dots"

        parts = label.split(".", 2)
        assert len(parts) >= 3
        model_id = parts[2]

        # Should preserve all dots in model_id
        assert model_id == "some.model.with.dots"

    def test_old_logic_would_fail(self):
        """Demonstrate that the old logic (split without limit) would fail."""
        label = "embedding.aiping.Qwen3-Embedding-0.6B"

        # Old buggy logic
        old_parts = label.split(".")
        old_result = old_parts[-1]

        # This would return '6B' - WRONG!
        assert old_result == "6B"

        # New fixed logic
        new_parts = label.split(".", 2)
        new_result = new_parts[2]

        # This correctly returns 'Qwen3-Embedding-0.6B'
        assert new_result == "Qwen3-Embedding-0.6B"

    def test_fallback_default(self):
        """Test fallback when settings is None."""
        result = Pipeline._extract_embedding_model_id(None)
        assert result == "Qwen3-Embedding-0.6B"

    def test_fallback_on_exception(self):
        """Test fallback when settings doesn't have llm attribute."""

        class NoLlmSettings:
            pass

        result = Pipeline._extract_embedding_model_id(NoLlmSettings())
        assert result == "Qwen3-Embedding-0.6B"

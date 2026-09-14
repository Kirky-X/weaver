# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T032: builder-level injection defenses."""

import pytest

from core.db.graph_query_builders import _clamp_confidence


class TestClampConfidence:
    def test_none_becomes_zero(self):
        assert _clamp_confidence(None) == 0.0

    def test_negative_clamped(self):
        assert _clamp_confidence(-0.5) == 0.0

    def test_above_one_clamped(self):
        assert _clamp_confidence(5.0) == 1.0

    def test_string_coerced(self):
        assert _clamp_confidence("0.5") == 0.5  # type: ignore[arg-type]


class TestParquetPathValidation:
    def test_rejects_quote(self):
        from modules.knowledge.cache.storage import KnowledgeCache

        with pytest.raises(ValueError):
            KnowledgeCache._validate_parquet_path("a'b.parquet")

    def test_rejects_semicolon(self):
        from modules.knowledge.cache.storage import KnowledgeCache

        with pytest.raises(ValueError):
            KnowledgeCache._validate_parquet_path("a;b")

    def test_rejects_comment_marker(self):
        from modules.knowledge.cache.storage import KnowledgeCache

        with pytest.raises(ValueError):
            KnowledgeCache._validate_parquet_path("a--b.parquet")

    def test_accepts_clean_path(self):
        from modules.knowledge.cache.storage import KnowledgeCache

        assert (
            KnowledgeCache._validate_parquet_path("data/.cache/sp.parquet")
            == "data/.cache/sp.parquet"
        )

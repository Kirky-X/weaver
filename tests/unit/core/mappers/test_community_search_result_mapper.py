# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for CommunitySearchResultMapper (OCR LOW #54).

``float(converted["score"])`` used to raise an unhelpful bare
``ValueError``/``TypeError`` for non-numeric scores. The mapper is a
reusable component, so it must surface a descriptive error instead.
"""

from __future__ import annotations

import pytest

from core.mappers.community_search_result_mapper import CommunitySearchResultMapper


class TestCommunitySearchResultMapper:
    """Tests for score coercion and error reporting."""

    @pytest.fixture
    def mapper(self) -> CommunitySearchResultMapper:
        return CommunitySearchResultMapper()

    def test_string_score_is_coerced(self, mapper: CommunitySearchResultMapper) -> None:
        view = mapper.to_view({"community_id": "c1", "score": "0.87"})
        assert view.score == pytest.approx(0.87)

    def test_numeric_score_passes_through(self, mapper: CommunitySearchResultMapper) -> None:
        view = mapper.to_view({"community_id": "c1", "score": 0.5})
        assert view.score == pytest.approx(0.5)

    def test_non_numeric_score_raises_descriptive_error(
        self, mapper: CommunitySearchResultMapper
    ) -> None:
        with pytest.raises(ValueError, match="Invalid score value: 'not-a-number'"):
            mapper.to_view({"community_id": "c1", "score": "not-a-number"})

    def test_error_chains_original_exception(self, mapper: CommunitySearchResultMapper) -> None:
        with pytest.raises(ValueError) as exc_info:
            mapper.to_view({"community_id": "c1", "score": "abc"})

        assert isinstance(exc_info.value.__cause__, (ValueError, TypeError))

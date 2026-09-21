# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Regression tests for PaginatedResponse.create validation.

``page`` and ``page_size`` must be positive integers. A non-positive value
must fail fast with ``ValueError`` rather than silently yielding
``total_pages = 0``.
"""

from __future__ import annotations

import pytest

from api.schemas.response import PaginatedResponse


class TestPaginatedResponseCreateValidation:
    """``create`` MUST reject non-positive page/page_size."""

    def test_positive_page_size_computes_pages(self) -> None:
        resp = PaginatedResponse.create(items=[], total=25, page=1, page_size=10)
        assert resp.total_pages == 3
        assert resp.page == 1
        assert resp.page_size == 10

    @pytest.mark.parametrize("page_size", [0, -1, -10])
    def test_zero_or_negative_page_size_raises(self, page_size: int) -> None:
        with pytest.raises(ValueError):
            PaginatedResponse.create(items=[], total=0, page=1, page_size=page_size)

    @pytest.mark.parametrize("page", [0, -1])
    def test_zero_or_negative_page_raises(self, page: int) -> None:
        with pytest.raises(ValueError):
            PaginatedResponse.create(items=[], total=0, page=page, page_size=10)

    def test_zero_total_with_valid_page_size_yields_zero_pages(self) -> None:
        resp = PaginatedResponse.create(items=[], total=0, page=1, page_size=20)
        assert resp.total_pages == 0

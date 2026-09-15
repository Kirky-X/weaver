# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors


"""Regression tests for fetcher exception chaining (T008 #177)."""

from __future__ import annotations

from modules.ingestion.fetching.exceptions import FetchError


class TestT008LowFixes:
    """Regression tests for T008 LOW findings (#177)."""

    def test_cause_is_linked_into_exception_chain(self):
        """#177: passing ``cause`` must populate ``__cause__`` like ``raise ... from``."""
        original = ValueError("boom")

        error = FetchError(url="https://example.com", message="failed", cause=original)

        assert error.cause is original
        assert error.__cause__ is original
        assert error.__suppress_context__ is True

    def test_without_cause_no_chain_is_invented(self):
        """#177: no cause means no synthetic ``__cause__``."""
        error = FetchError(url="https://example.com", message="failed")

        assert error.__cause__ is None

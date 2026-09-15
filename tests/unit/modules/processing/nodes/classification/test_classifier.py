# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors


"""Regression tests for URL-pattern precompilation."""

from __future__ import annotations

import inspect
import re

from modules.processing.nodes.classification import classifier as module


class TestT008LowFixes:
    """Regression tests for LOW findings."""

    def test_news_url_patterns_are_precompiled(self):
        """#85: the module-level patterns are compiled once."""
        assert len(module._NEWS_URL_REGEXES) == len(module.NEWS_URL_PATTERNS)
        assert all(isinstance(p, re.Pattern) for p in module._NEWS_URL_REGEXES)

        src = inspect.getsource(module.CascadeClassifierNode._rule_classify)
        assert "_NEWS_URL_REGEXES" in src
        assert "re.search(pattern, url)" not in src

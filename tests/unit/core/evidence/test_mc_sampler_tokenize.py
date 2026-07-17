# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""RED test for MCSampler word-level tokenization — P1-2 fix.

``_simple_similarity`` currently uses ``set(text1)`` (character-level),
which gives false-high similarity for unrelated Chinese text (many
common characters) and false-non-zero for Chinese vs Latin (no shared
characters but meaningless). Word-level tokenization fixes both:

- Chinese: 2-gram sliding window over CJK runs (``技术发展`` →
  ``{技术, 术发, 发展}``)
- English: ``re.findall(r'[a-zA-Z]+', text)``

See ``temp/report.md`` P1-2 (MC 采样器 tokenize) and specmark change
``fix-pipeline-deadcode-perf`` T018-T019.
"""

from __future__ import annotations

import pytest


class TestMCSamplerTokenizeSimilarity:
    """Tests for _simple_similarity with word-level tokenization."""

    @pytest.fixture
    def sampler(self):
        """Create MCSampler instance for testing _simple_similarity."""
        from core.evidence.mc_sampler import MCSampler

        # _simple_similarity is a pure method; we only need an instance.
        # MCSampler.__init__ may require deps, so we instantiate via
        # __new__ to bypass __init__.
        sampler = MCSampler.__new__(MCSampler)
        return sampler

    def test_chinese_shared_bigram_nonzero_similarity(self, sampler) -> None:
        """``技术发展`` and ``发展快速`` share ``发展`` → non-zero similarity."""
        sim = sampler._simple_similarity("技术发展", "发展快速")
        assert sim > 0.0, f"Expected non-zero similarity (shared bigram '发展'); got {sim}"

    def test_chinese_vs_english_zero_similarity(self, sampler) -> None:
        """``技术发展`` and ``abcdef`` share no tokens → zero similarity."""
        sim = sampler._simple_similarity("技术发展", "abcdef")
        assert sim == 0.0, f"Expected zero similarity (no shared tokens); got {sim}"

    def test_english_shared_word_nonzero_similarity(self, sampler) -> None:
        """``hello world`` and ``world peace`` share ``world`` → non-zero."""
        sim = sampler._simple_similarity("hello world", "world peace")
        assert sim > 0.0, f"Expected non-zero similarity (shared word 'world'); got {sim}"

    def test_english_disjoint_zero_similarity(self, sampler) -> None:
        """``alpha beta`` and ``gamma delta`` share no words → zero."""
        sim = sampler._simple_similarity("alpha beta", "gamma delta")
        assert sim == 0.0, f"Expected zero similarity; got {sim}"

    def test_empty_string_zero_similarity(self, sampler) -> None:
        """Empty string → zero similarity (regression guard)."""
        assert sampler._simple_similarity("", "anything") == 0.0
        assert sampler._simple_similarity("anything", "") == 0.0
        assert sampler._simple_similarity("", "") == 0.0

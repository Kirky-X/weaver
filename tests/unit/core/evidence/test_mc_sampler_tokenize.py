# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""RED test for MCSampler word-level tokenization

``_simple_similarity`` currently uses ``set(text1)`` (character-level),
which gives false-high similarity for unrelated Chinese text (many
common characters) and false-non-zero for Chinese vs Latin (no shared
characters but meaningless). Word-level tokenization fixes both:

- Chinese: 2-gram sliding window over CJK runs (``技术发展`` →
  ``{技术, 术发, 发展}``)
- English: ``re.findall(r'[a-zA-Z]+', text)``
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


class TestFindFuzzAnchorsEdgeCases:
    """``_find_fuzz_anchors`` 边界与 tokenizer 复用（OCR LOW #25/#91/#115）。"""

    @pytest.fixture
    def sampler(self):
        from core.evidence.mc_sampler import MCSampler

        return MCSampler.__new__(MCSampler)

    def test_zero_window_returns_no_anchors(self, sampler) -> None:
        """window == 0 时必须直接返回 []，不得把每个步进点都当成变化点。

        短文本（text_len < 10）会算出 window == 0，此前切片得到空串、
        相似度恒为 0.0 (< 0.5)，导致每个步进位置都被误判为锚点。
        """
        assert sampler._find_fuzz_anchors("a" * 50, window=0) == []
        assert sampler._find_fuzz_anchors("short", window=-1) == []

    def test_negative_window_returns_no_anchors(self, sampler) -> None:
        assert sampler._find_fuzz_anchors("x" * 500, window=-5) == []

    def test_tokenize_uses_module_level_patterns(self) -> None:
        """tokenizer 复用模块级预编译正则（OCR LOW #25），行为不变。"""
        from core.evidence import mc_sampler

        assert hasattr(mc_sampler, "_WORD_RE")
        assert hasattr(mc_sampler, "_CJK_RUN_RE")
        tokens = mc_sampler.MCSampler._tokenize("hello world 技术发展")
        assert "hello" in tokens
        assert "world" in tokens
        assert "技术" in tokens
        assert "发展" in tokens

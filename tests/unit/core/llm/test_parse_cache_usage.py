# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for _parse_cache_usage unified cache usage parser."""

import pytest

from core.llm.types import CacheUsage, _parse_cache_usage


class TestParseDeepSeekFormat:
    """Tests for DeepSeek top-level cache field parsing."""

    def test_deepseek_standard_format(self) -> None:
        """DeepSeek 顶层字段正确解析为 CacheUsage."""
        raw = {
            "prompt_cache_hit_tokens": 500,
            "prompt_cache_miss_tokens": 200,
            "prompt_tokens": 700,
        }
        usage = _parse_cache_usage(raw)
        assert usage.cache_hit_tokens == 500
        assert usage.cache_miss_tokens == 200
        assert usage.cache_hit_rate == pytest.approx(500 / 700)

    def test_deepseek_full_hit(self) -> None:
        """DeepSeek 全命中场景."""
        raw = {
            "prompt_cache_hit_tokens": 1000,
            "prompt_cache_miss_tokens": 0,
        }
        usage = _parse_cache_usage(raw)
        assert usage.cache_hit_tokens == 1000
        assert usage.cache_miss_tokens == 0
        assert usage.cache_hit_rate == 1.0

    def test_deepseek_full_miss(self) -> None:
        """DeepSeek 全未命中场景（hit=0, miss>0 仍属 DeepSeek 格式）."""
        raw = {
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 700,
        }
        usage = _parse_cache_usage(raw)
        assert usage.cache_hit_tokens == 0
        assert usage.cache_miss_tokens == 700
        assert usage.cache_hit_rate == 0.0


class TestParseOpenAIFallback:
    """Tests for OpenAI nested cache field fallback parsing."""

    def test_openai_nested_format_fallback(self) -> None:
        """OpenAI 嵌套格式回退解析，miss 从 prompt_tokens - hit 推导."""
        raw = {
            "prompt_tokens": 700,
            "prompt_tokens_details": {"cached_tokens": 300},
        }
        usage = _parse_cache_usage(raw)
        assert usage.cache_hit_tokens == 300
        assert usage.cache_miss_tokens == 400  # 700 - 300

    def test_openai_no_cached_tokens(self) -> None:
        """OpenAI 格式但 cached_tokens=0 时回退为全 0."""
        raw = {
            "prompt_tokens": 500,
            "prompt_tokens_details": {"cached_tokens": 0},
        }
        usage = _parse_cache_usage(raw)
        assert usage.cache_hit_tokens == 0
        assert usage.cache_miss_tokens == 0

    def test_deepseek_zero_falls_back_to_openai(self) -> None:
        """DeepSeek 字段全为 0 时回退到 OpenAI 嵌套格式."""
        raw = {
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
            "prompt_tokens": 800,
            "prompt_tokens_details": {"cached_tokens": 200},
        }
        usage = _parse_cache_usage(raw)
        assert usage.cache_hit_tokens == 200
        assert usage.cache_miss_tokens == 600  # 800 - 200


class TestParseReasoningTokens:
    """Tests for reasoning_tokens extraction."""

    def test_reasoning_tokens_extracted(self) -> None:
        """reasoning_tokens 从 completion_tokens_details 正确提取."""
        raw = {
            "prompt_cache_hit_tokens": 100,
            "prompt_cache_miss_tokens": 50,
            "completion_tokens_details": {"reasoning_tokens": 150},
        }
        usage = _parse_cache_usage(raw)
        assert usage.reasoning_tokens == 150

    def test_reasoning_tokens_absent(self) -> None:
        """无 completion_tokens_details 时 reasoning_tokens=0."""
        raw = {
            "prompt_cache_hit_tokens": 100,
            "prompt_cache_miss_tokens": 50,
        }
        usage = _parse_cache_usage(raw)
        assert usage.reasoning_tokens == 0

    def test_reasoning_tokens_with_openai_fallback(self) -> None:
        """OpenAI 回退路径下 reasoning_tokens 仍可提取."""
        raw = {
            "prompt_tokens": 700,
            "prompt_tokens_details": {"cached_tokens": 300},
            "completion_tokens_details": {"reasoning_tokens": 80},
        }
        usage = _parse_cache_usage(raw)
        assert usage.cache_hit_tokens == 300
        assert usage.reasoning_tokens == 80


class TestParseNoCacheFields:
    """Tests for graceful degradation when no cache fields present."""

    def test_ollama_no_cache_fields(self) -> None:
        """无任何 cache 字段的 provider（如 Ollama）返回全 0，不抛异常."""
        raw = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        usage = _parse_cache_usage(raw)
        assert usage.cache_hit_tokens == 0
        assert usage.cache_miss_tokens == 0
        assert usage.reasoning_tokens == 0
        assert usage.cache_hit_rate == 0.0

    def test_empty_dict(self) -> None:
        """空字典返回全 0."""
        usage = _parse_cache_usage({})
        assert usage.cache_hit_tokens == 0
        assert usage.cache_miss_tokens == 0
        assert usage.reasoning_tokens == 0

    def test_none_values_treated_as_zero(self) -> None:
        """字段值为 None 时按 0 处理."""
        raw = {
            "prompt_cache_hit_tokens": None,
            "prompt_cache_miss_tokens": None,
        }
        usage = _parse_cache_usage(raw)
        assert usage.cache_hit_tokens == 0
        assert usage.cache_miss_tokens == 0

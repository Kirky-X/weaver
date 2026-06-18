# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for LLM input truncation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm.utils.input_truncation import INPUT_LIMITS, truncate_input


class TestTruncateInput:
    """Test truncate_input function."""

    def test_truncate_with_title(self):
        body = "这是正文内容。" * 200
        result = truncate_input("classifier", body, title="测试标题")
        assert result.startswith("标题：测试标题")
        assert "正文：" in result
        assert len(result) > len("标题：测试标题\n\n正文：")
        assert len(result) <= len("标题：测试标题\n\n正文：") + INPUT_LIMITS["classifier"]

    def test_truncate_without_title(self):
        body = "这是正文内容。" * 200
        result = truncate_input("classifier", body)
        assert result == body[: INPUT_LIMITS["classifier"]]
        assert len(result) == INPUT_LIMITS["classifier"]

    def test_body_shorter_than_limit(self):
        body = "短文本"
        result = truncate_input("classifier", body, title="标题")
        expected = f"标题：标题\n\n正文：{body}"
        assert result == expected

    def test_body_at_limit(self):
        body = "a" * INPUT_LIMITS["classifier"]
        result = truncate_input("classifier", body)
        assert result == body
        assert len(result) == INPUT_LIMITS["classifier"]

    def test_body_exceeds_limit(self):
        body = "a" * (INPUT_LIMITS["classifier"] + 100)
        result = truncate_input("classifier", body)
        assert len(result) == INPUT_LIMITS["classifier"]
        assert result == "a" * INPUT_LIMITS["classifier"]

    def test_default_limit_for_unknown_call_point(self):
        body = "a" * 5000
        result = truncate_input("unknown_point", body)
        assert len(result) == INPUT_LIMITS["default"]

    def test_title_with_unicode(self):
        body = "这是一个包含 Unicode 的正文内容。" * 100
        result = truncate_input("classifier", body, title="中文标题")
        assert "标题：中文标题" in result

    def test_empty_body(self):
        result = truncate_input("classifier", "", title="标题")
        assert result == "标题：标题\n\n正文："


class TestInputLimits:
    """Test INPUT_LIMITS configuration."""

    def test_classifier_limit(self):
        assert INPUT_LIMITS["classifier"] == 600

    def test_categorizer_limit(self):
        assert INPUT_LIMITS["categorizer"] == 1100

    def test_analyze_limit(self):
        assert INPUT_LIMITS["analyze"] == 3000

    def test_quality_scorer_limit(self):
        assert INPUT_LIMITS["quality_scorer"] == 1500

    def test_credibility_checker_limit(self):
        assert INPUT_LIMITS["credibility_checker"] == 2000

    def test_summary_limit(self):
        assert INPUT_LIMITS["summary"] == 2000

    def test_entity_extractor_limit(self):
        assert INPUT_LIMITS["entity_extractor"] == 2000

    def test_default_limit(self):
        assert INPUT_LIMITS["default"] == 2000


class TestTruncationIntegration:
    """Test truncation integration in LLMClient.call()."""

    @pytest.mark.asyncio
    async def test_body_truncated_before_execute(self):
        from core.llm.client import LLMClient
        from core.llm.types import GlobalConfig, Label, LLMType, ProviderConfig, TokenUsage

        providers = [
            ProviderConfig(
                name="openai",
                type="openai",
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                rpm_limit=100,
                concurrency=5,
                timeout=30.0,
                priority=100,
                weight=100,
                models={},
            )
        ]
        global_config = GlobalConfig(
            circuit_breaker_threshold=5,
            circuit_breaker_timeout=60.0,
            default_timeout=120.0,
        )
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        client = LLMClient(providers=providers, global_config=global_config, event_bus=event_bus)

        long_body = "测试正文内容。" * 1000
        payload = {
            "body": long_body,
            "title": "测试文章标题",
        }

        with patch.object(client._pools["openai"], "execute", new=AsyncMock()) as mock_execute:
            mock_execute.return_value = MagicMock(
                content="result",
                token_usage=TokenUsage(input_tokens=10, output_tokens=20),
                label=Label(llm_type=LLMType.CHAT, provider="openai", model="gpt-4o"),
                latency_ms=100.0,
                model="gpt-4o",
                cache_hit_tokens=0,
                cache_miss_tokens=0,
            )
            await client.call("chat.openai.gpt-4o", payload, call_point="classifier")

        actual_payload = mock_execute.call_args[1]["payload"]
        assert len(actual_payload["body"]) <= 600 + len("标题：测试文章标题\n\n正文：")
        assert "标题：测试文章标题" in actual_payload["body"]
        assert "正文：" in actual_payload["body"]

    @pytest.mark.asyncio
    async def test_no_body_field_not_affected(self):
        from core.llm.client import LLMClient
        from core.llm.types import GlobalConfig, Label, LLMType, ProviderConfig, TokenUsage

        providers = [
            ProviderConfig(
                name="openai",
                type="openai",
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                rpm_limit=100,
                concurrency=5,
                timeout=30.0,
                priority=100,
                weight=100,
                models={},
            )
        ]
        global_config = GlobalConfig(
            circuit_breaker_threshold=5,
            circuit_breaker_timeout=60.0,
            default_timeout=120.0,
        )
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        client = LLMClient(providers=providers, global_config=global_config, event_bus=event_bus)

        payload = {"messages": [{"role": "user", "content": "hello"}]}

        with patch.object(client._pools["openai"], "execute", new=AsyncMock()) as mock_execute:
            mock_execute.return_value = MagicMock(
                content="result",
                token_usage=TokenUsage(input_tokens=10, output_tokens=20),
                label=Label(llm_type=LLMType.CHAT, provider="openai", model="gpt-4o"),
                latency_ms=100.0,
                model="gpt-4o",
                cache_hit_tokens=0,
                cache_miss_tokens=0,
            )
            await client.call("chat.openai.gpt-4o", payload, call_point="classifier")

        actual_payload = mock_execute.call_args[1]["payload"]
        assert actual_payload == payload

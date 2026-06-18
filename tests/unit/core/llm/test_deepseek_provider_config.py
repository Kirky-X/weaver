# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for DeepSeek provider configuration in config/llm.toml (Task 9)."""

import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[4]
LLM_TOML_PATH = PROJECT_ROOT / "config" / "llm.toml"


@pytest.fixture
def llm_toml_data():
    """Load the actual config/llm.toml file."""
    with open(LLM_TOML_PATH, "rb") as f:
        return tomllib.load(f)


class TestDeepSeekProviderConfig:
    """Test DeepSeek provider configuration exists in llm.toml."""

    def test_deepseek_provider_section_exists(self, llm_toml_data):
        """[providers.deepseek] 配置段存在."""
        providers = llm_toml_data.get("providers", {})
        assert "deepseek" in providers, "DeepSeek provider not found in llm.toml"

    def test_deepseek_provider_has_required_fields(self, llm_toml_data):
        """DeepSeek provider 包含必要字段: name, type, base_url, api_key."""
        deepseek = llm_toml_data["providers"]["deepseek"]
        assert deepseek.get("name") == "deepseek"
        assert deepseek.get("type") == "openai"
        assert "base_url" in deepseek
        assert deepseek["base_url"].startswith("https://")

    def test_deepseek_no_hardcoded_api_key(self, llm_toml_data):
        """配置文件中无明文 API key（api_key 为空字符串）."""
        deepseek = llm_toml_data["providers"]["deepseek"]
        api_key = deepseek.get("api_key", "")
        assert api_key == "", f"DeepSeek api_key should be empty, got: {api_key}"

    def test_deepseek_has_chat_model(self, llm_toml_data):
        """DeepSeek provider 配置了 chat 模型."""
        deepseek = llm_toml_data["providers"]["deepseek"]
        models = deepseek.get("models", {})
        assert "chat" in models, "DeepSeek provider should have a chat model"
        chat_model = models["chat"]
        assert "model_id" in chat_model
        assert "max_tokens" in chat_model
        assert "chat" in chat_model.get("capabilities", [])


class TestDeepSeekFallbackConfig:
    """Test DeepSeek is configured as fallback for some call_points."""

    def test_some_call_points_have_deepseek_fallback(self, llm_toml_data):
        """部分 call_point 配置了 DeepSeek fallback."""
        call_points = llm_toml_data.get("call-points", {})
        deepseek_fallback_count = 0
        for cp_name, cp_config in call_points.items():
            fallbacks = cp_config.get("fallbacks", [])
            for fb in fallbacks:
                if "deepseek" in fb.lower():
                    deepseek_fallback_count += 1

        assert deepseek_fallback_count > 0, (
            "No call_points have DeepSeek as fallback. "
            "Expected at least classifier, analyze, or entity_extractor."
        )

    def test_classifier_has_deepseek_fallback(self, llm_toml_data):
        """classifier call_point 配置了 DeepSeek fallback."""
        call_points = llm_toml_data.get("call-points", {})
        classifier = call_points.get("classifier", {})
        fallbacks = classifier.get("fallbacks", [])
        has_deepseek = any("deepseek" in fb.lower() for fb in fallbacks)
        assert has_deepseek, "classifier should have DeepSeek in fallbacks"

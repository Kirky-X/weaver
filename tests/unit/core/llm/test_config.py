# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for LLM config loader."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.llm.config import ConfigLoadError, LLMConfigLoader
from core.llm.types import LLMType


class TestLLMConfigLoader:
    """Tests for LLMConfigLoader."""

    def test_load_nonexistent_file(self) -> None:
        """Test loading nonexistent file raises error."""
        with pytest.raises(ConfigLoadError, match="Config file not found"):
            LLMConfigLoader.load("/nonexistent/path.toml")

    def test_load_valid_config(self, tmp_path: Path) -> None:
        """Test loading valid config file."""
        config_content = """
[global]
circuit_breaker_threshold = 5
circuit_breaker_timeout = 60.0

[providers.aiping]
type = "openai"
base_url = "https://www.aiping.cn/api/v1"
api_key = "test-key"
rpm_limit = 100

  [providers.aiping.models.chat]
  model_id = "GLM-4-9B-0414"
  capabilities = ["chat"]

[defaults.chat]
label = "chat.aiping.GLM-4-9B-0414"
fallbacks = []
"""
        config_file = tmp_path / "llm.toml"
        config_file.write_text(config_content)

        providers, global_config = LLMConfigLoader.load(str(config_file))

        assert len(providers) == 1
        assert providers[0].name == "aiping"
        assert providers[0].type == "openai"
        assert "chat" in providers[0].models
        assert providers[0].models["chat"].model_id == "GLM-4-9B-0414"

        assert LLMType.CHAT in global_config.defaults
        assert global_config.defaults[LLMType.CHAT].primary == "chat.aiping.GLM-4-9B-0414"

    def test_env_var_resolution(self, tmp_path: Path) -> None:
        """Test environment variable resolution."""
        with patch.dict(os.environ, {"TEST_API_KEY": "secret-key"}):
            config_content = """
[providers.test]
type = "openai"
api_key = "${TEST_API_KEY}"
base_url = "https://api.test.com/v1"

  [providers.test.models.chat]
  model_id = "test-model"
"""
            config_file = tmp_path / "llm.toml"
            config_file.write_text(config_content)

            providers, _ = LLMConfigLoader.load(str(config_file))

            assert providers[0].api_key == "secret-key"

    def test_env_var_with_default(self, tmp_path: Path) -> None:
        """Test environment variable with default value."""
        config_content = """
[providers.test]
type = "openai"
api_key = "${NONEXISTENT_KEY:-default-key}"
base_url = "https://api.test.com/v1"

  [providers.test.models.chat]
  model_id = "test-model"
"""
        config_file = tmp_path / "llm.toml"
        config_file.write_text(config_content)

        providers, _ = LLMConfigLoader.load(str(config_file))

        assert providers[0].api_key == "default-key"

    def test_call_points_parsing(self, tmp_path: Path) -> None:
        """Test call points parsing."""
        config_content = """
[global]

[providers.aiping]
type = "openai"
api_key = "test"
base_url = ""

  [providers.aiping.models.chat]
  model_id = "GLM-4-9B"

[call-points.classifier]
primary = "chat.aiping.GLM-4-9B"
fallbacks = ["chat.openai.gpt-4o"]

[call-points.cleaner]
primary = "chat.aiping.GLM-4-9B"
fallbacks = []
"""
        config_file = tmp_path / "llm.toml"
        config_file.write_text(config_content)

        _, global_config = LLMConfigLoader.load(str(config_file))

        assert "classifier" in global_config.call_points
        assert global_config.call_points["classifier"].primary == "chat.aiping.GLM-4-9B"
        assert len(global_config.call_points["classifier"].fallbacks) == 1
        assert "cleaner" in global_config.call_points

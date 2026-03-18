# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for PromptLoader."""

from pathlib import Path
from unittest.mock import mock_open, patch

from core.prompt.loader import PromptLoader


class TestPromptLoader:
    """Tests for PromptLoader."""

    def test_initialization(self):
        """Test prompt loader initializes with path."""
        loader = PromptLoader("config/prompts")
        assert loader._path == Path("config/prompts")
        assert loader._cache == {}

    def test_get_system_prompt(self):
        """Test getting system prompt from TOML file."""
        toml_content = b"""
version = "1.0.0"
system = "You are a helpful assistant."
user = "Please help me."
"""
        with patch("builtins.open", mock_open(read_data=toml_content)):
            loader = PromptLoader("config/prompts")
            result = loader.get("test_prompt", "system")
            assert result == "You are a helpful assistant."

    def test_get_version(self):
        """Test getting version from TOML file."""
        toml_content = b"""
version = "2.1.0"
system = "Test prompt"
"""
        with patch("builtins.open", mock_open(read_data=toml_content)):
            loader = PromptLoader("config/prompts")
            version = loader.get_version("test_prompt")
            assert version == "2.1.0"

    def test_get_version_unknown_when_missing(self):
        """Test version returns 'unknown' when not specified."""
        toml_content = b"""
system = "Test prompt"
"""
        with patch("builtins.open", mock_open(read_data=toml_content)):
            loader = PromptLoader("config/prompts")
            version = loader.get_version("test_prompt")
            assert version == "unknown"

    def test_caching(self):
        """Test that loaded prompts are cached."""
        toml_content = b"""
version = "1.0.0"
system = "Cached prompt"
"""
        with patch("builtins.open", mock_open(read_data=toml_content)) as mock_file:
            loader = PromptLoader("config/prompts")
            loader.get("test", "system")
            loader.get("test", "system")
            loader.get("test", "version")
            mock_file.assert_called_once()

    def test_get_user_prompt(self):
        """Test getting user prompt from TOML file."""
        toml_content = b"""
version = "1.0.0"
system = "System prompt"
user = "User prompt"
"""
        with patch("builtins.open", mock_open(read_data=toml_content)):
            loader = PromptLoader("config/prompts")
            result = loader.get("test", "user")
            assert result == "User prompt"

    def test_get_default_key(self):
        """Test getting default key (system) when not specified."""
        toml_content = b"""
version = "1.0.0"
system = "Default system prompt"
"""
        with patch("builtins.open", mock_open(read_data=toml_content)):
            loader = PromptLoader("config/prompts")
            result = loader.get("test")
            assert result == "Default system prompt"

    def test_path_conversion(self):
        """Test path is converted to Path object."""
        loader = PromptLoader("config/prompts")
        assert isinstance(loader._path, Path)

    def test_cache_populated_after_get(self):
        """Test cache is populated after first get."""
        toml_content = b"""
version = "1.0.0"
system = "Test"
"""
        with patch("builtins.open", mock_open(read_data=toml_content)):
            loader = PromptLoader("config/prompts")
            assert "test_prompt" not in loader._cache
            loader.get("test_prompt")
            assert "test_prompt" in loader._cache

    def test_multiple_prompts_cached_separately(self):
        """Test multiple prompts are cached separately."""
        toml_content_1 = b'version = "1.0"\nsystem = "Prompt 1"'
        toml_content_2 = b'version = "2.0"\nsystem = "Prompt 2"'

        def side_effect_open(file, *args, **kwargs):
            if "prompt1" in str(file):
                return mock_open(read_data=toml_content_1)()
            elif "prompt2" in str(file):
                return mock_open(read_data=toml_content_2)()
            return mock_open(read_data=b"")()

        with patch("builtins.open", side_effect=side_effect_open):
            loader = PromptLoader("config/prompts")
            result1 = loader.get("prompt1")
            result2 = loader.get("prompt2")
            assert result1 == "Prompt 1"
            assert result2 == "Prompt 2"

    def test_toml_with_multiline_string(self):
        """Test TOML with multiline string."""
        toml_content = b'''
version = "1.0.0"
system = """
This is a multiline
system prompt.
"""
'''
        with patch("builtins.open", mock_open(read_data=toml_content)):
            loader = PromptLoader("config/prompts")
            result = loader.get("test")
            assert "multiline" in result

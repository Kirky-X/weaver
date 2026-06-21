# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for pydantic-settings compatibility.

These tests ensure that our settings_customise_sources implementations
remain compatible with pydantic-settings v2.x API.
"""

import pytest
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class TestPydanticSettingsCompatibility:
    """Test pydantic-settings API compatibility."""

    def test_settings_customise_sources_signature(self):
        """Test that settings_customise_sources has correct signature.

        pydantic-settings 2.13.1+ passes these exact parameter names:
        - settings_cls
        - init_settings
        - env_settings
        - dotenv_settings
        - file_secret_settings (NOT _file_secret_settings)

        This test verifies our implementations match the expected signature.
        """
        import inspect

        from config.settings import Settings
        from core.llm.config.config import LLMSettings
        from modules.processing.pipeline.config import PipelineSettings

        # Check Settings
        sig = inspect.signature(Settings.settings_customise_sources)
        params = list(sig.parameters.keys())
        assert "file_secret_settings" in params, (
            f"Settings.settings_customise_sources must have 'file_secret_settings' parameter. "
            f"Found: {params}"
        )
        assert "_file_secret_settings" not in params, (
            "Settings.settings_customise_sources must NOT have '_file_secret_settings' "
            "(underscore prefix causes TypeError in pydantic-settings 2.13.1+)"
        )

        # Check LLMSettings
        sig = inspect.signature(LLMSettings.settings_customise_sources)
        params = list(sig.parameters.keys())
        assert "file_secret_settings" in params, (
            f"LLMSettings.settings_customise_sources must have 'file_secret_settings' parameter. "
            f"Found: {params}"
        )

        # Check PipelineSettings
        sig = inspect.signature(PipelineSettings.settings_customise_sources)
        params = list(sig.parameters.keys())
        assert "file_secret_settings" in params, (
            f"PipelineSettings.settings_customise_sources must have 'file_secret_settings' parameter. "
            f"Found: {params}"
        )

    def test_settings_instantiation(self):
        """Test that Settings can be instantiated without TypeError.

        This is a regression test for the issue where incorrect parameter
        names in settings_customise_sources caused:
        TypeError: Settings.settings_customise_sources() got an unexpected
        keyword argument 'file_secret_settings'
        """
        from config.settings import Settings

        # This should not raise TypeError
        settings = Settings()

        # Basic validation
        assert settings is not None
        assert hasattr(settings, "app_name")
        assert hasattr(settings, "memory")

    def test_llm_settings_instantiation(self):
        """Test that LLMSettings can be instantiated without TypeError."""
        from core.llm.config.config import LLMSettings

        # This should not raise TypeError
        llm_settings = LLMSettings()

        assert llm_settings is not None

    def test_pipeline_settings_instantiation(self):
        """Test that PipelineSettings can be instantiated without TypeError."""
        from modules.processing.pipeline.config import PipelineSettings

        # This should not raise TypeError
        pipeline_settings = PipelineSettings()

        assert pipeline_settings is not None

    def test_pydantic_settings_version(self):
        """Test that pydantic-settings version is in compatible range."""
        import pydantic_settings
        from packaging import version

        current_version = version.parse(pydantic_settings.__version__)
        min_version = version.parse("2.13.1")
        max_version = version.parse("3.0.0")

        assert current_version >= min_version, (
            f"pydantic-settings version {pydantic_settings.__version__} is too old. "
            f"Minimum required: 2.13.1"
        )
        assert current_version < max_version, (
            f"pydantic-settings version {pydantic_settings.__version__} may have breaking changes. "
            f"Maximum supported: <3.0.0. Please verify settings_customise_sources compatibility."
        )

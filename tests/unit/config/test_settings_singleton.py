# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Test Settings singleton is unified between config.settings and container.

Validates GAP-M05 fix: config.settings.get_settings() delegates to
container.get_settings(), ensuring a single Settings instance.
"""

from unittest.mock import patch

import pytest


class TestSettingsSingleton:
    """Verify config.settings.get_settings() and container.get_settings() return same instance."""

    def test_config_get_settings_delegates_to_container(self) -> None:
        """config.settings.get_settings() should return the same instance as container.get_settings()."""
        # Reset container singleton for clean test
        import container
        from config.settings import get_settings as config_get_settings
        from container import get_settings as container_get_settings

        container.reset_settings()

        # Both should return the same instance
        settings = config_get_settings()
        container_settings = container_get_settings()
        assert (
            settings is container_settings
        ), "config.settings.get_settings() and container.get_settings() should return the same instance"

        # Cleanup
        container.reset_settings()

    def test_config_get_settings_creates_instance_when_container_uninitialized(self) -> None:
        """config.settings.get_settings() should create a new Settings when container is uninitialized."""
        import container

        container.reset_settings()

        from config.settings import get_settings

        settings = get_settings()
        assert settings is not None

        # Cleanup
        container.reset_settings()

    def test_no_separate_settings_instance_in_config(self) -> None:
        """config.settings should NOT have its own _settings_instance separate from container."""
        import config.settings

        # After the fix, config.settings should NOT have _settings_instance
        assert (
            not hasattr(config.settings, "_settings_instance")
            or config.settings._settings_instance is None
        ), "config.settings should not maintain its own _settings_instance"

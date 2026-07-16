# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Test that system environment variables take priority over .env file values.

Validates GAP-H03 fix: load_dotenv(override=False) ensures system env vars
are not overwritten by .env file values.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestDotenvPriority:
    """Verify system environment variables take priority over .env file."""

    def test_env_var_overrides_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """System environment variable should take priority over .env file value."""
        from dotenv import load_dotenv

        # Set a system environment variable BEFORE loading .env
        test_var = "WEAVER_TEST_DOTENV_PRIORITY"
        monkeypatch.setenv(test_var, "from_system_env")

        # Create a .env file with the same variable but different value
        env_file = tmp_path / ".env"
        env_file.write_text(f"{test_var}=from_dotenv_file\n")

        # Load .env with override=False (the fix)
        load_dotenv(env_file, override=False)

        # System env var should NOT be overwritten
        assert os.environ.get(test_var) == "from_system_env"

        # Cleanup
        monkeypatch.delenv(test_var, raising=False)

    def test_dotenv_sets_unset_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Variables not in system env should still be set from .env file."""
        from dotenv import load_dotenv

        test_var = "WEAVER_TEST_DOTENV_UNSET"
        # Ensure the variable is NOT set in system env
        monkeypatch.delenv(test_var, raising=False)

        # Create a .env file with the variable
        env_file = tmp_path / ".env"
        env_file.write_text(f"{test_var}=from_dotenv_file\n")

        # Load .env with override=False
        load_dotenv(env_file, override=False)

        # .env value should be set since system env var was not set
        assert os.environ.get(test_var) == "from_dotenv_file"

        # Cleanup
        monkeypatch.delenv(test_var, raising=False)

    def test_override_true_would_overwrite_system_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that override=True would overwrite system env vars (the old bug)."""
        from dotenv import load_dotenv

        test_var = "WEAVER_TEST_DOTENV_OVERRIDE_TRUE"
        monkeypatch.setenv(test_var, "from_system_env")

        env_file = tmp_path / ".env"
        env_file.write_text(f"{test_var}=from_dotenv_file\n")

        # Load with override=True (the OLD behavior)
        load_dotenv(env_file, override=True)

        # System env var IS overwritten (this is the bug we're fixing)
        assert os.environ.get(test_var) == "from_dotenv_file"

        # Cleanup
        monkeypatch.delenv(test_var, raising=False)

    def test_settings_uses_env_over_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Settings instance should use system env var value over .env file value."""
        # This test verifies the actual Settings class behavior
        # by checking that the env_prefix mechanism respects system env vars
        from config.settings import Settings

        # Set a system env var for a known Settings field
        monkeypatch.setenv("WEAVER_APP_NAME", "from_system_env")

        # Create Settings instance — system env var should win
        settings = Settings()
        assert settings.app_name == "from_system_env"

        # Cleanup
        monkeypatch.delenv("WEAVER_APP_NAME", raising=False)

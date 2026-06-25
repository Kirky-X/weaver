# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for core.nlp.spacy_manager module."""

from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from core.nlp.spacy_manager import SpacyModelConfig, SpacyModelManager


class TestSpacyModelConfig:
    """Test SpacyModelConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SpacyModelConfig()

        assert config.force_install is False
        assert config.strict_mode is True
        assert config.models == ["zh_core_web_lg", "en_core_web_lg"]
        assert config.local_paths == {}

    def test_custom_config(self):
        """Test custom configuration values."""
        config = SpacyModelConfig(
            force_install=True,
            strict_mode=False,
            models=["en_core_web_lg"],
            local_paths={"en_core_web_lg": "/path/to/model.whl"},
        )

        assert config.force_install is True
        assert config.strict_mode is False
        assert config.models == ["en_core_web_lg"]
        assert config.local_paths == {"en_core_web_lg": "/path/to/model.whl"}


class TestSpacyModelManagerInit:
    """Test SpacyModelManager initialization."""

    def test_init_stores_config(self):
        """Test __init__ stores config."""
        config = SpacyModelConfig()
        manager = SpacyModelManager(config)

        assert manager._config is config


class TestSpacyModelManagerDetectMissing:
    """Test SpacyModelManager._detect_missing_models."""

    def test_detects_no_missing_models(self):
        """Test detects when all models are present."""
        config = SpacyModelConfig(models=["en_core_web_lg"])
        manager = SpacyModelManager(config)

        with patch("spacy.load") as mock_load:
            mock_load.return_value = MagicMock()

            missing = manager._detect_missing_models()

            assert missing == []
            mock_load.assert_called_once_with("en_core_web_lg")

    def test_detects_missing_models(self):
        """Test detects missing models."""
        config = SpacyModelConfig(models=["en_core_web_lg", "zh_core_web_lg"])
        manager = SpacyModelManager(config)

        def mock_load(model):
            if model == "en_core_web_lg":
                return MagicMock()
            raise OSError(f"Model {model} not found")

        with patch("spacy.load", side_effect=mock_load):
            missing = manager._detect_missing_models()

            assert missing == ["zh_core_web_lg"]

    def test_detects_multiple_missing_models(self):
        """Test detects multiple missing models."""
        config = SpacyModelConfig(models=["model1", "model2", "model3"])
        manager = SpacyModelManager(config)

        with patch("spacy.load", side_effect=OSError("Not found")):
            missing = manager._detect_missing_models()

            assert missing == ["model1", "model2", "model3"]


class TestSpacyModelManagerCheckAndInstall:
    """Test SpacyModelManager.check_and_install."""

    def test_returns_when_all_present(self):
        """Test returns early when all models present."""
        config = SpacyModelConfig(models=["en_core_web_lg"])
        manager = SpacyModelManager(config)

        with patch.object(manager, "_detect_missing_models", return_value=[]):
            with patch("core.nlp.spacy_manager.log") as mock_log:
                manager.check_and_install()

                mock_log.info.assert_called_once()

    def test_warns_when_missing_but_no_force_install(self):
        """Test warns when models missing but force_install=False."""
        config = SpacyModelConfig(
            models=["en_core_web_lg"],
            force_install=False,
        )
        manager = SpacyModelManager(config)

        with patch.object(manager, "_detect_missing_models", return_value=["en_core_web_lg"]):
            with patch("core.nlp.spacy_manager.log") as mock_log:
                manager.check_and_install()

                mock_log.warning.assert_called_once()

    def test_installs_when_force_enabled(self):
        """Test installs models when force_install=True."""
        config = SpacyModelConfig(
            models=["en_core_web_lg"],
            force_install=True,
        )
        manager = SpacyModelManager(config)

        with patch.object(manager, "_detect_missing_models", return_value=["en_core_web_lg"]):
            with patch.object(manager, "_install_model") as mock_install:
                manager.check_and_install()

                mock_install.assert_called_once_with("en_core_web_lg")


class TestSpacyModelManagerInstallModel:
    """Test SpacyModelManager._install_model."""

    def test_installs_from_local_path(self):
        """Test installs from local wheel file."""
        config = SpacyModelConfig(
            local_paths={"en_core_web_lg": "/path/model.whl"},
        )
        manager = SpacyModelManager(config)

        with patch("pathlib.Path.exists", return_value=True):
            with patch.object(manager, "_install_from_local") as mock_install:
                manager._install_model("en_core_web_lg")

                mock_install.assert_called_once_with("en_core_web_lg", "/path/model.whl")

    def test_falls_back_to_network_when_local_missing(self):
        """Test falls back to network download when local path doesn't exist."""
        config = SpacyModelConfig(
            local_paths={"en_core_web_lg": "/missing/model.whl"},
        )
        manager = SpacyModelManager(config)

        with patch("pathlib.Path.exists", return_value=False):
            with patch.object(manager, "_install_from_network") as mock_install:
                manager._install_model("en_core_web_lg")

                mock_install.assert_called_once_with("en_core_web_lg")

    def test_installs_from_network_when_no_local_config(self):
        """Test installs from network when no local path configured."""
        config = SpacyModelConfig()
        manager = SpacyModelManager(config)

        with patch.object(manager, "_install_from_network") as mock_install:
            manager._install_model("en_core_web_lg")

            mock_install.assert_called_once_with("en_core_web_lg")

    def test_raises_on_install_failure_in_strict_mode(self):
        """Test raises RuntimeError on installation failure in strict mode."""
        config = SpacyModelConfig(strict_mode=True)
        manager = SpacyModelManager(config)

        # Mock _install_from_network to call _handle_install_failure like real code does
        def mock_install_from_network(model):
            manager._handle_install_failure(model, "Download failed")

        with patch.object(manager, "_install_from_network", side_effect=mock_install_from_network):
            with pytest.raises(RuntimeError, match="Failed to install"):
                manager._install_model("en_core_web_lg")

    def test_logs_warning_on_install_failure_in_non_strict_mode(self):
        """Test logs warning on installation failure in non-strict mode."""
        config = SpacyModelConfig(strict_mode=False)
        manager = SpacyModelManager(config)

        # Mock _install_from_network to call _handle_install_failure like real code does
        def mock_install_from_network(model):
            manager._handle_install_failure(model, "Download failed")

        with patch.object(manager, "_install_from_network", side_effect=mock_install_from_network):
            with patch("core.nlp.spacy_manager.log") as mock_log:
                manager._install_model("en_core_web_lg")

                mock_log.error.assert_called_once()


class TestSpacyModelManagerInstallFromLocal:
    """Test SpacyModelManager._install_from_local."""

    def test_installs_via_pip(self):
        """Test installs local wheel via pip."""
        config = SpacyModelConfig()
        manager = SpacyModelManager(config)

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.suffix", new_callable=lambda: property(lambda self: ".whl")),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)

            manager._install_from_local("en_core_web_lg", "/path/model.whl")

            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "pip" in call_args[0] or "uv" in call_args[0]

    def test_raises_on_pip_failure(self):
        """Test raises on pip installation failure."""
        config = SpacyModelConfig(strict_mode=True)
        manager = SpacyModelManager(config)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "pip install failed"
        mock_result.stdout = ""

        # Mock Path to simulate a valid .whl file
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.is_file.return_value = True
        mock_path.suffix = ".whl"
        mock_path.resolve.return_value = mock_path
        mock_path.__str__ = lambda self: "/path/model.whl"

        with (
            patch("core.nlp.spacy_manager.Path", return_value=mock_path),
            patch("subprocess.run", return_value=mock_result),
            patch.object(
                manager, "_install_from_network", side_effect=RuntimeError("network failed")
            ),
        ):
            with pytest.raises(RuntimeError, match="Failed to install spaCy model"):
                manager._install_from_local("en_core_web_lg", "/path/model.whl")


class TestSpacyModelManagerInstallFromNetwork:
    """Test SpacyModelManager._install_from_network."""

    def test_downloads_via_spacy_cli(self):
        """Test downloads model via spacy CLI."""
        config = SpacyModelConfig()
        manager = SpacyModelManager(config)

        with patch("spacy.cli.download") as mock_download:
            manager._install_from_network("en_core_web_lg")

            mock_download.assert_called_once_with("en_core_web_lg")

    def test_raises_on_download_failure(self):
        """Test raises on download failure."""
        config = SpacyModelConfig(strict_mode=True)
        manager = SpacyModelManager(config)

        with patch("spacy.cli.download", side_effect=SystemExit(1)):
            with pytest.raises(RuntimeError):
                manager._install_from_network("en_core_web_lg")


class TestSpacyModelManagerIntegration:
    """Integration tests for SpacyModelManager."""

    def test_full_workflow_all_present(self):
        """Test full workflow when all models present."""
        config = SpacyModelConfig(models=["en_core_web_lg"])
        manager = SpacyModelManager(config)

        with patch("spacy.load", return_value=MagicMock()):
            with patch("core.nlp.spacy_manager.log") as mock_log:
                manager.check_and_install()

                mock_log.info.assert_called_once()

    def test_full_workflow_force_install(self):
        """Test full workflow with force_install enabled."""
        config = SpacyModelConfig(
            models=["en_core_web_lg"],
            force_install=True,
        )
        manager = SpacyModelManager(config)

        def mock_load(model):
            raise OSError("Not found")

        with patch("spacy.load", side_effect=mock_load):
            with patch("spacy.cli.download") as mock_download:
                manager.check_and_install()

                mock_download.assert_called_once()

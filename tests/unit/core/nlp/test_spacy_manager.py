# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SpacyModelManager."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.nlp.spacy_manager import SpacyModelConfig, SpacyModelManager


class TestSpacyModelConfig:
    """Tests for SpacyModelConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SpacyModelConfig()

        assert config.force_install is False
        assert config.strict_mode is True
        assert config.models == ["zh_core_web_lg", "en_core_web_sm"]
        assert config.local_paths == {}

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = SpacyModelConfig(
            force_install=True,
            strict_mode=False,
            models=["zh_core_web_trf"],
            local_paths={"zh_core_web_trf": "/path/to/model.whl"},
        )

        assert config.force_install is True
        assert config.strict_mode is False
        assert config.models == ["zh_core_web_trf"]
        assert config.local_paths == {"zh_core_web_trf": "/path/to/model.whl"}


class TestSpacyModelManagerInit:
    """Tests for SpacyModelManager initialization."""

    def test_init_with_config(self) -> None:
        """Test initialization with config."""
        config = SpacyModelConfig(force_install=True)
        manager = SpacyModelManager(config)

        assert manager._config is config


class TestDetectMissingModels:
    """Tests for _detect_missing_models method."""

    def test_all_models_present(self) -> None:
        """Test when all models are installed."""
        config = SpacyModelConfig(models=["zh_core_web_lg", "en_core_web_sm"])
        manager = SpacyModelManager(config)

        with patch("spacy.load") as mock_load:
            mock_load.return_value = MagicMock()  # All models load successfully
            missing = manager._detect_missing_models()

        assert missing == []

    def test_some_models_missing(self) -> None:
        """Test when some models are missing."""
        config = SpacyModelConfig(models=["zh_core_web_lg", "en_core_web_sm"])
        manager = SpacyModelManager(config)

        with patch("spacy.load") as mock_load:
            # First call succeeds, second fails
            mock_load.side_effect = [MagicMock(), OSError("Model not found")]
            missing = manager._detect_missing_models()

        assert missing == ["en_core_web_sm"]

    def test_all_models_missing(self) -> None:
        """Test when all models are missing."""
        config = SpacyModelConfig(models=["zh_core_web_lg", "en_core_web_sm"])
        manager = SpacyModelManager(config)

        with patch("spacy.load") as mock_load:
            mock_load.side_effect = OSError("Model not found")
            missing = manager._detect_missing_models()

        assert set(missing) == {"zh_core_web_lg", "en_core_web_sm"}


class TestInstallFromLocal:
    """Tests for _install_from_local method."""

    def _mock_uv_module(self) -> MagicMock:
        """Create a mock uv module."""
        mock_uv = MagicMock()
        mock_uv.find_uv_bin.return_value = "/path/to/uv"
        return mock_uv

    def test_install_success(self, tmp_path: Path) -> None:
        """Test successful installation from local wheel."""
        config = SpacyModelConfig()
        manager = SpacyModelManager(config)

        # Create a dummy wheel file
        wheel_path = tmp_path / "model.whl"
        wheel_path.touch()

        mock_uv = self._mock_uv_module()
        with (
            patch.dict(sys.modules, {"uv": mock_uv}),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)

            # Should not raise
            manager._install_from_local("zh_core_web_lg", str(wheel_path))

            mock_run.assert_called_once()

    def test_install_failure_strict_mode(self, tmp_path: Path) -> None:
        """Test installation failure in strict mode."""
        config = SpacyModelConfig(strict_mode=True)
        manager = SpacyModelManager(config)

        wheel_path = tmp_path / "model.whl"
        wheel_path.touch()

        mock_uv = self._mock_uv_module()
        with (
            patch.dict(sys.modules, {"uv": mock_uv}),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stderr="Install failed")

            with pytest.raises(RuntimeError, match="Failed to install spaCy model"):
                manager._install_from_local("zh_core_web_lg", str(wheel_path))

    def test_install_failure_non_strict_mode(self, tmp_path: Path) -> None:
        """Test installation failure in non-strict mode."""
        config = SpacyModelConfig(strict_mode=False)
        manager = SpacyModelManager(config)

        wheel_path = tmp_path / "model.whl"
        wheel_path.touch()

        mock_uv = self._mock_uv_module()
        with (
            patch.dict(sys.modules, {"uv": mock_uv}),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stderr="Install failed")

            # Should not raise in non-strict mode
            manager._install_from_local("zh_core_web_lg", str(wheel_path))


class TestInstallFromNetwork:
    """Tests for _install_from_network method."""

    def test_install_success(self) -> None:
        """Test successful network installation."""
        config = SpacyModelConfig()
        manager = SpacyModelManager(config)

        with patch("spacy.cli.download") as mock_download:
            mock_download.return_value = None  # Success

            # Should not raise
            manager._install_from_network("en_core_web_sm")

            mock_download.assert_called_once_with("en_core_web_sm")

    def test_install_failure_strict_mode(self) -> None:
        """Test network installation failure in strict mode."""
        config = SpacyModelConfig(strict_mode=True)
        manager = SpacyModelManager(config)

        with patch("spacy.cli.download") as mock_download:
            mock_download.side_effect = SystemExit(1)

            with pytest.raises(RuntimeError, match="Failed to install spaCy model"):
                manager._install_from_network("en_core_web_sm")

    def test_install_failure_non_strict_mode(self) -> None:
        """Test network installation failure in non-strict mode."""
        config = SpacyModelConfig(strict_mode=False)
        manager = SpacyModelManager(config)

        with patch("spacy.cli.download") as mock_download:
            mock_download.side_effect = SystemExit(1)

            # Should not raise in non-strict mode
            manager._install_from_network("en_core_web_sm")


class TestHandleInstallFailure:
    """Tests for _handle_install_failure method."""

    def test_strict_mode_raises(self) -> None:
        """Test that strict mode raises RuntimeError."""
        config = SpacyModelConfig(strict_mode=True)
        manager = SpacyModelManager(config)

        with pytest.raises(RuntimeError, match="Failed to install spaCy model"):
            manager._handle_install_failure("zh_core_web_lg", "Connection failed")

    def test_non_strict_mode_logs(self) -> None:
        """Test that non-strict mode logs error without raising."""
        config = SpacyModelConfig(strict_mode=False)
        manager = SpacyModelManager(config)

        with patch("core.nlp.spacy_manager.log") as mock_log:
            # Should not raise
            manager._handle_install_failure("zh_core_web_lg", "Connection failed")

            mock_log.error.assert_called_once()


class TestCheckAndInstall:
    """Tests for check_and_install method."""

    def test_all_models_present(self) -> None:
        """Test when all models are present."""
        config = SpacyModelConfig(force_install=True)
        manager = SpacyModelManager(config)

        with patch.object(manager, "_detect_missing_models", return_value=[]):
            # Should not raise, just log success
            manager.check_and_install()

    def test_missing_models_force_install_false(self) -> None:
        """Test missing models when force_install is False."""
        config = SpacyModelConfig(force_install=False)
        manager = SpacyModelManager(config)

        with (
            patch.object(manager, "_detect_missing_models", return_value=["zh_core_web_lg"]),
            patch("core.nlp.spacy_manager.log") as mock_log,
        ):
            manager.check_and_install()

            # Should log warning, not install
            mock_log.warning.assert_called_once()

    def test_missing_models_force_install_true(self) -> None:
        """Test missing models when force_install is True."""
        config = SpacyModelConfig(force_install=True)
        manager = SpacyModelManager(config)

        with (
            patch.object(manager, "_detect_missing_models", return_value=["zh_core_web_lg"]),
            patch.object(manager, "_install_model") as mock_install,
        ):
            manager.check_and_install()

            # Should call install for each missing model
            mock_install.assert_called_once_with("zh_core_web_lg")

    def test_multiple_missing_models_install_serially(self) -> None:
        """Test that multiple missing models are installed serially."""
        config = SpacyModelConfig(force_install=True)
        manager = SpacyModelManager(config)

        with (
            patch.object(
                manager, "_detect_missing_models", return_value=["zh_core_web_lg", "en_core_web_sm"]
            ),
            patch.object(manager, "_install_model") as mock_install,
        ):
            manager.check_and_install()

            # Should call install for each model in order
            assert mock_install.call_count == 2
            mock_install.assert_any_call("zh_core_web_lg")
            mock_install.assert_any_call("en_core_web_sm")


class TestInstallModel:
    """Tests for _install_model method."""

    def test_install_from_local_when_configured(self, tmp_path: Path) -> None:
        """Test that local path is used when configured and file exists."""
        wheel_path = tmp_path / "model.whl"
        wheel_path.touch()

        config = SpacyModelConfig(local_paths={"zh_core_web_lg": str(wheel_path)})
        manager = SpacyModelManager(config)

        with patch.object(manager, "_install_from_local") as mock_local:
            manager._install_model("zh_core_web_lg")

            mock_local.assert_called_once_with("zh_core_web_lg", str(wheel_path))

    def test_install_from_network_when_local_not_configured(self) -> None:
        """Test that network is used when local path not configured."""
        config = SpacyModelConfig(local_paths={})
        manager = SpacyModelManager(config)

        with patch.object(manager, "_install_from_network") as mock_network:
            manager._install_model("en_core_web_sm")

            mock_network.assert_called_once_with("en_core_web_sm")

    def test_install_from_network_when_local_file_not_exists(self) -> None:
        """Test that network is used when local file doesn't exist."""
        config = SpacyModelConfig(local_paths={"zh_core_web_lg": "/nonexistent/path.whl"})
        manager = SpacyModelManager(config)

        with patch.object(manager, "_install_from_network") as mock_network:
            manager._install_model("zh_core_web_lg")

            mock_network.assert_called_once_with("zh_core_web_lg")

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for centralized path constants."""

from pathlib import Path

from core.utils.paths import CACHE_DIR, CONFIG_DIR, DATA_DIR, PROJECT_ROOT, data_path


class TestProjectRoot:
    """Tests for PROJECT_ROOT constant."""

    def test_is_absolute(self):
        """PROJECT_ROOT must be an absolute path."""
        assert isinstance(PROJECT_ROOT, Path)
        assert PROJECT_ROOT.is_absolute()

    def test_points_to_project_root(self):
        """PROJECT_ROOT must point to the project root (parent of src/)."""
        assert (PROJECT_ROOT / "src").is_dir()
        assert (PROJECT_ROOT / "config").is_dir()
        assert (PROJECT_ROOT / "pyproject.toml").exists() or (PROJECT_ROOT / "setup.py").exists()


class TestDataDir:
    """Tests for DATA_DIR constant."""

    def test_is_absolute(self):
        """DATA_DIR must be an absolute path."""
        assert isinstance(DATA_DIR, Path)
        assert DATA_DIR.is_absolute()

    def test_is_under_project_root(self):
        """DATA_DIR must be PROJECT_ROOT / "data"."""
        assert DATA_DIR == PROJECT_ROOT / "data"


class TestConfigDir:
    """Tests for CONFIG_DIR constant."""

    def test_is_absolute(self):
        """CONFIG_DIR must be an absolute path."""
        assert isinstance(CONFIG_DIR, Path)
        assert CONFIG_DIR.is_absolute()

    def test_is_under_project_root(self):
        """CONFIG_DIR must be PROJECT_ROOT / "config"."""
        assert CONFIG_DIR == PROJECT_ROOT / "config"


class TestCacheDir:
    """Tests for CACHE_DIR constant."""

    def test_is_absolute(self):
        """CACHE_DIR must be an absolute path."""
        assert isinstance(CACHE_DIR, Path)
        assert CACHE_DIR.is_absolute()

    def test_is_under_data_dir(self):
        """CACHE_DIR must be DATA_DIR / ".cache"."""
        assert CACHE_DIR == DATA_DIR / ".cache"


class TestDataPath:
    """Tests for data_path helper function."""

    def test_returns_absolute_string(self):
        """data_path must return an absolute string."""
        result = data_path("weaver.duckdb")
        assert isinstance(result, str)
        assert Path(result).is_absolute()

    def test_joins_with_data_dir(self):
        """data_path must join filename with DATA_DIR."""
        result = data_path("weaver.duckdb")
        assert result == str(DATA_DIR / "weaver.duckdb")

    def test_multiple_filenames(self):
        """data_path must work with different filenames."""
        assert data_path("phishtank.json") == str(DATA_DIR / "phishtank.json")
        assert data_path("weaver.lbug") == str(DATA_DIR / "weaver.lbug")

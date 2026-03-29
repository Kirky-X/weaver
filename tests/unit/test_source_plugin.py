# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for source plugin system."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.source.plugin import (
    PluginMetadata,
    _plugin_registry,
    discover_plugins_from_directory,
    discover_plugins_from_entry_points,
    get_plugin,
    get_registered_plugins,
    scan_and_load_external_plugins,
    source_parser_plugin,
)


class TestPluginMetadata:
    """Tests for PluginMetadata dataclass."""

    def test_default_values(self):
        """Test default initialization."""
        meta = PluginMetadata(name="test_plugin")
        assert meta.name == "test_plugin"
        assert meta.version == "1.0.0"
        assert meta.description == ""
        assert meta.author == ""
        assert meta.supported_types == []
        assert meta.capabilities == []

    def test_custom_values(self):
        """Test custom initialization."""
        meta = PluginMetadata(
            name="custom_plugin",
            version="2.0.0",
            description="A custom parser",
            author="Developer",
            supported_types=["rss", "atom"],
            capabilities=["incremental", "streaming"],
        )
        assert meta.name == "custom_plugin"
        assert meta.version == "2.0.0"
        assert meta.description == "A custom parser"
        assert meta.author == "Developer"
        assert meta.supported_types == ["rss", "atom"]
        assert meta.capabilities == ["incremental", "streaming"]


class TestSourceParserPlugin:
    """Tests for source_parser_plugin decorator."""

    def setup_method(self):
        """Clear registry before each test."""
        _plugin_registry.clear()

    def test_decorator_registers_class(self):
        """Test that decorator registers the class."""

        @source_parser_plugin(name="test_parser")
        class TestParser:
            pass

        assert "test_parser" in _plugin_registry
        parser_cls, meta = _plugin_registry["test_parser"]
        assert parser_cls is TestParser
        assert meta.name == "test_parser"

    def test_decorator_with_all_params(self):
        """Test decorator with all parameters."""

        @source_parser_plugin(
            name="full_parser",
            version="3.0.0",
            description="Full featured parser",
            author="Test Author",
            supported_types=["type1", "type2"],
            capabilities=["cap1", "cap2"],
        )
        class FullParser:
            pass

        _, meta = _plugin_registry["full_parser"]
        assert meta.version == "3.0.0"
        assert meta.description == "Full featured parser"
        assert meta.author == "Test Author"
        assert meta.supported_types == ["type1", "type2"]
        assert meta.capabilities == ["cap1", "cap2"]

    def test_decorator_returns_original_class(self):
        """Test that decorator returns the original class."""

        @source_parser_plugin(name="return_test")
        class OriginalClass:
            value = 42

        assert OriginalClass.value == 42


class TestGetRegisteredPlugins:
    """Tests for get_registered_plugins function."""

    def setup_method(self):
        """Clear registry before each test."""
        _plugin_registry.clear()

    def test_empty_registry(self):
        """Test with empty registry."""
        _plugin_registry.clear()
        plugins = get_registered_plugins()
        assert plugins == {}

    def test_returns_metadata_only(self):
        """Test that only metadata is returned."""

        @source_parser_plugin(name="meta_test")
        class TestParser:
            pass

        plugins = get_registered_plugins()
        assert "meta_test" in plugins
        assert isinstance(plugins["meta_test"], PluginMetadata)


class TestGetPlugin:
    """Tests for get_plugin function."""

    def setup_method(self):
        """Clear registry before each test."""
        _plugin_registry.clear()

    def test_get_existing_plugin(self):
        """Test getting an existing plugin."""

        @source_parser_plugin(name="existing")
        class ExistingParser:
            pass

        result = get_plugin("existing")
        assert result is not None
        parser_cls, meta = result
        assert parser_cls is ExistingParser
        assert meta.name == "existing"

    def test_get_nonexistent_plugin(self):
        """Test getting a nonexistent plugin."""
        result = get_plugin("nonexistent")
        assert result is None


class TestDiscoverPluginsFromDirectory:
    """Tests for discover_plugins_from_directory function."""

    def test_nonexistent_directory(self):
        """Test with nonexistent directory."""
        result = discover_plugins_from_directory("/nonexistent/path")
        assert result == []

    def test_empty_directory(self):
        """Test with empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = discover_plugins_from_directory(tmpdir)
            assert result == []

    def test_directory_with_invalid_files(self):
        """Test directory with non-Python files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create non-Python file
            Path(tmpdir, "readme.txt").write_text("not a plugin")
            # Create underscored Python file (should be skipped)
            Path(tmpdir, "_private.py").write_text("# private module")

            result = discover_plugins_from_directory(tmpdir)
            assert result == []

    def test_directory_with_valid_plugin(self):
        """Test directory with valid plugin file."""
        _plugin_registry.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_code = """
from modules.source.plugin import source_parser_plugin

@source_parser_plugin(name="file_plugin")
class FileParser:
    pass
"""
            plugin_path = Path(tmpdir, "file_plugin.py")
            plugin_path.write_text(plugin_code)

            result = discover_plugins_from_directory(tmpdir)
            # Plugin should be loaded
            assert len(result) > 0 or "file_plugin" in _plugin_registry


class TestDiscoverPluginsFromEntryPoints:
    """Tests for discover_plugins_from_entry_points function."""

    def test_no_entry_points(self):
        """Test when no entry points are defined."""
        # Mock the entry_points function to avoid API compatibility issues
        with patch("importlib.metadata.entry_points") as mock_eps:
            # Return object that supports .get() or dict-like access
            mock_eps.return_value = {}
            result = discover_plugins_from_entry_points()
            assert isinstance(result, list)

    def test_with_valid_entry_point(self):
        """Test with valid entry point."""
        mock_entry = MagicMock()
        mock_entry.name = "test_plugin"
        mock_entry.load.return_value = lambda: "ParserClass"

        with patch("importlib.metadata.entry_points") as mock_eps:
            # Use dict-like object for compatibility
            mock_eps.return_value = {"weaver_source_parsers": [mock_entry]}
            result = discover_plugins_from_entry_points()
            assert isinstance(result, list)

    def test_import_error(self):
        """Test handling ImportError when importlib.metadata unavailable."""
        with patch("importlib.metadata.entry_points", side_effect=ImportError()):
            result = discover_plugins_from_entry_points()
            assert result == []


class TestScanAndLoadExternalPlugins:
    """Tests for scan_and_load_external_plugins function."""

    def test_no_config_paths_no_env(self):
        """Test with no config paths and no env variable."""
        # Should not raise
        with patch.dict(os.environ, {"WEAVER_SOURCE_PLUGINS": ""}, clear=True):
            scan_and_load_external_plugins()

    def test_with_config_paths(self):
        """Test with explicit config paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Should not raise even with empty directory
            scan_and_load_external_plugins(config_paths=[tmpdir])

    def test_with_env_variable(self):
        """Test with WEAVER_SOURCE_PLUGINS env variable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"WEAVER_SOURCE_PLUGINS": tmpdir}):
                scan_and_load_external_plugins()
                # Should process the directory


class TestPluginIntegration:
    """Integration tests for plugin system."""

    def setup_method(self):
        """Clear registry before each test."""
        _plugin_registry.clear()

    def test_full_plugin_workflow(self):
        """Test complete plugin workflow."""

        # 1. Register plugin via decorator
        @source_parser_plugin(
            name="workflow_parser",
            version="1.5.0",
            supported_types=["rss"],
        )
        class WorkflowParser:
            def parse(self):
                return []

        # 2. Check it's registered
        assert "workflow_parser" in get_registered_plugins()

        # 3. Get plugin
        result = get_plugin("workflow_parser")
        assert result is not None

        parser_cls, meta = result
        assert meta.version == "1.5.0"
        assert "rss" in meta.supported_types

    def test_multiple_plugins(self):
        """Test registering multiple plugins."""

        @source_parser_plugin(name="plugin_a")
        class PluginA:
            pass

        @source_parser_plugin(name="plugin_b")
        class PluginB:
            pass

        plugins = get_registered_plugins()
        assert "plugin_a" in plugins
        assert "plugin_b" in plugins

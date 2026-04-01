# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for source parser plugin system."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.ingestion.parsing.plugin import (
    PluginMetadata,
    discover_plugins_from_directory,
    discover_plugins_from_entry_points,
    get_plugin,
    get_registered_plugins,
    scan_and_load_external_plugins,
    source_parser_plugin,
)


class TestPluginMetadata:
    """Tests for PluginMetadata dataclass."""

    def test_plugin_metadata_defaults(self):
        """Test default metadata values."""
        metadata = PluginMetadata(name="test_plugin")

        assert metadata.name == "test_plugin"
        assert metadata.version == "1.0.0"
        assert metadata.description == ""
        assert metadata.author == ""
        assert metadata.supported_types == []
        assert metadata.capabilities == []

    def test_plugin_metadata_full(self):
        """Test metadata with all fields."""
        metadata = PluginMetadata(
            name="my_plugin",
            version="2.0.0",
            description="A test plugin",
            author="Test Author",
            supported_types=["rss", "atom"],
            capabilities=["incremental", "streaming"],
        )

        assert metadata.name == "my_plugin"
        assert metadata.version == "2.0.0"
        assert metadata.description == "A test plugin"
        assert metadata.author == "Test Author"
        assert metadata.supported_types == ["rss", "atom"]
        assert metadata.capabilities == ["incremental", "streaming"]


class TestSourceParserPluginDecorator:
    """Tests for source_parser_plugin decorator."""

    def setup_method(self):
        """Clear registry before each test."""
        from modules.ingestion.parsing import plugin

        plugin._plugin_registry.clear()
        plugin._plugin_decorators.clear()

    def test_decorator_registers_plugin(self):
        """Test that decorator registers plugin."""
        from modules.ingestion.parsing import plugin

        @source_parser_plugin(name="test_plugin")
        class TestParser:
            pass

        assert "test_plugin" in plugin._plugin_registry
        assert plugin._plugin_registry["test_plugin"][0] is TestParser

    def test_decorator_with_metadata(self):
        """Test decorator with full metadata."""
        from modules.ingestion.parsing import plugin

        @source_parser_plugin(
            name="full_plugin",
            version="1.5.0",
            description="Full plugin",
            author="Author",
            supported_types=["custom"],
            capabilities=["feature1"],
        )
        class FullParser:
            pass

        _, metadata = plugin._plugin_registry["full_plugin"]
        assert metadata.version == "1.5.0"
        assert metadata.description == "Full plugin"
        assert metadata.author == "Author"
        assert metadata.supported_types == ["custom"]
        assert metadata.capabilities == ["feature1"]

    def test_decorator_returns_original_class(self):
        """Test decorator returns original class."""

        @source_parser_plugin(name="return_test")
        class OriginalClass:
            pass

        assert OriginalClass.__name__ == "OriginalClass"


class TestGetRegisteredPlugins:
    """Tests for get_registered_plugins function."""

    def setup_method(self):
        """Clear registry before each test."""
        from modules.ingestion.parsing import plugin

        plugin._plugin_registry.clear()

    def test_get_registered_plugins_empty(self):
        """Test with empty registry."""
        plugins = get_registered_plugins()
        assert plugins == {}

    def test_get_registered_plugins_with_plugins(self):
        """Test with registered plugins."""
        from modules.ingestion.parsing import plugin

        @source_parser_plugin(name="plugin1", version="1.0.0")
        class Parser1:
            pass

        @source_parser_plugin(name="plugin2", version="2.0.0")
        class Parser2:
            pass

        plugins = get_registered_plugins()

        assert len(plugins) == 2
        assert plugins["plugin1"].version == "1.0.0"
        assert plugins["plugin2"].version == "2.0.0"


class TestGetPlugin:
    """Tests for get_plugin function."""

    def setup_method(self):
        """Clear registry before each test."""
        from modules.ingestion.parsing import plugin

        plugin._plugin_registry.clear()

    def test_get_plugin_found(self):
        """Test getting existing plugin."""
        from modules.ingestion.parsing import plugin

        @source_parser_plugin(name="get_test")
        class TestParser:
            pass

        result = get_plugin("get_test")

        assert result is not None
        parser_class, metadata = result
        assert parser_class is TestParser
        assert metadata.name == "get_test"

    def test_get_plugin_not_found(self):
        """Test getting non-existent plugin."""
        result = get_plugin("non_existent")
        assert result is None


class TestDiscoverPluginsFromDirectory:
    """Tests for discover_plugins_from_directory function."""

    def setup_method(self):
        """Clear registry before each test."""
        from modules.ingestion.parsing import plugin

        plugin._plugin_registry.clear()

    def test_discover_from_nonexistent_directory(self):
        """Test with non-existent directory."""
        result = discover_plugins_from_directory("/nonexistent/path")
        assert result == []

    def test_discover_from_empty_directory(self):
        """Test with empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = discover_plugins_from_directory(tmpdir)
            assert result == []

    def test_discover_from_directory_with_plugin(self):
        """Test discovering plugin from directory."""
        from modules.ingestion.parsing import plugin

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a plugin file with create_parser function
            plugin_file = Path(tmpdir) / "test_parser.py"
            plugin_file.write_text("""
from modules.ingestion.parsing.plugin import source_parser_plugin

@source_parser_plugin(name="discovered_plugin")
class DiscoveredParser:
    pass

def create_parser():
    return DiscoveredParser()
""")

            result = discover_plugins_from_directory(tmpdir)

            # Should have loaded the plugin (with create_parser function)
            assert len(result) > 0

    def test_discover_skips_underscore_files(self):
        """Test that __init__.py and similar are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create __init__.py
            init_file = Path(tmpdir) / "__init__.py"
            init_file.write_text("# Init file")

            result = discover_plugins_from_directory(tmpdir)

            # Should not load __init__.py
            assert result == []

    def test_discover_handles_invalid_plugin(self):
        """Test handling of plugin with syntax error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create invalid plugin file
            plugin_file = Path(tmpdir) / "invalid.py"
            plugin_file.write_text("this is not valid python syntax !!!")

            result = discover_plugins_from_directory(tmpdir)

            # Should not crash, just skip
            assert result == []


class TestDiscoverPluginsFromEntryPoints:
    """Tests for discover_plugins_from_entry_points function."""

    def setup_method(self):
        """Clear registry before each test."""
        from modules.ingestion.parsing import plugin

        plugin._plugin_registry.clear()

    def test_discover_from_entry_points_no_entry_points(self):
        """Test with no entry points available."""
        with patch("importlib.metadata.entry_points") as mock_eps:
            mock_eps.return_value = {}

            result = discover_plugins_from_entry_points()

            assert result == []

    def test_discover_from_entry_points_with_valid_plugin(self):
        """Test discovering valid plugin from entry points."""
        mock_ep = MagicMock()
        mock_ep.name = "test_plugin"
        mock_ep.load.return_value = lambda: None

        with patch("importlib.metadata.entry_points") as mock_eps:
            mock_eps.return_value = {"weaver_source_parsers": [mock_ep]}

            result = discover_plugins_from_entry_points()

            assert "test_plugin" in result

    def test_discover_from_entry_points_with_load_error(self):
        """Test handling entry point load error."""
        mock_ep = MagicMock()
        mock_ep.name = "broken_plugin"
        mock_ep.load.side_effect = ImportError("Cannot load")

        with patch("importlib.metadata.entry_points") as mock_eps:
            mock_eps.return_value = {"weaver_source_parsers": [mock_ep]}

            result = discover_plugins_from_entry_points()

            # Should not crash, just skip
            assert result == []

    def test_discover_from_entry_points_import_error(self):
        """Test handling when importlib.metadata not available."""
        with patch("importlib.metadata.entry_points", side_effect=ImportError()):
            result = discover_plugins_from_entry_points()

            assert result == []


class TestScanAndLoadExternalPlugins:
    """Tests for scan_and_load_external_plugins function."""

    def setup_method(self):
        """Clear registry before each test."""
        from modules.ingestion.parsing import plugin

        plugin._plugin_registry.clear()

    def test_scan_with_config_paths(self):
        """Test scanning with configured paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a plugin file
            plugin_file = Path(tmpdir) / "ext_plugin.py"
            plugin_file.write_text("""
from modules.ingestion.parsing.plugin import source_parser_plugin

@source_parser_plugin(name="external_plugin")
class ExternalParser:
    pass
""")

            with patch(
                "modules.ingestion.parsing.plugin.discover_plugins_from_directory"
            ) as mock_discover:
                mock_discover.return_value = ["external_plugin"]

                scan_and_load_external_plugins(config_paths=[tmpdir])

                mock_discover.assert_called_once_with(tmpdir)

    def test_scan_with_env_var(self):
        """Test scanning with environment variable paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"WEAVER_SOURCE_PLUGINS": tmpdir}):
                with patch(
                    "modules.ingestion.parsing.plugin.discover_plugins_from_directory"
                ) as mock_discover:
                    mock_discover.return_value = []

                    scan_and_load_external_plugins()

                    mock_discover.assert_called_once_with(tmpdir)

    def test_scan_with_empty_env(self):
        """Test scanning with empty environment variable."""
        with patch.dict(os.environ, {"WEAVER_SOURCE_PLUGINS": ""}, clear=True):
            with patch(
                "modules.ingestion.parsing.plugin.discover_plugins_from_directory"
            ) as mock_discover:
                mock_discover.return_value = []

                scan_and_load_external_plugins()

                mock_discover.assert_not_called()

    def test_scan_with_multiple_paths(self):
        """Test scanning multiple paths."""
        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                paths = f"{tmpdir1}{os.pathsep}{tmpdir2}"

                with patch.dict(os.environ, {"WEAVER_SOURCE_PLUGINS": paths}):
                    with patch(
                        "modules.ingestion.parsing.plugin.discover_plugins_from_directory"
                    ) as mock_discover:
                        mock_discover.return_value = []

                        scan_and_load_external_plugins()

                        assert mock_discover.call_count == 2

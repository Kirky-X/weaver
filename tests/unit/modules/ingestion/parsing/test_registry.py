# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Unit tests for SourceRegistry."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSourceRegistryInit:
    """Tests for SourceRegistry initialization."""

    def test_init_registers_default_parsers(self):
        """Test SourceRegistry registers default parsers."""
        from modules.ingestion.parsing.registry import SourceRegistry

        mock_fetcher = MagicMock()
        registry = SourceRegistry(fetcher=mock_fetcher)

        assert "rss" in registry.list_registered_types()
        assert "newsnow" in registry.list_registered_types()

    def test_atom_type_resolves_to_rss_parser(self):
        """The declared 'atom' source type must resolve to a parser.

        The metadata advertises Atom support, but get_parser() is an exact
        dict lookup — registering only the "rss" key made every atom source
        fail with no_parser_for_type at crawl time.
        """
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=MagicMock())

        assert "atom" in registry.list_registered_types()
        assert registry.get_parser("atom") is not None
        assert registry.get_parser("atom") is registry.get_parser("rss")

    def test_every_registered_parser_type_is_reachable(self):
        """Every type in list_registered_types() must return a parser."""
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=MagicMock())

        for source_type in registry.list_registered_types():
            assert registry.get_parser(source_type) is not None, source_type


class TestRegisteredTypesConstant:
    """Tests pinning core.constants.REGISTERED_TYPES to the registry.

    REGISTERED_TYPES is the API-side declaration of what can be crawled; the
    registry is the runtime truth. If they drift, a source type is either
    rejected despite working, or accepted and then silently never crawled.
    """

    def test_registered_types_constant_matches_registry(self):
        """REGISTERED_TYPES must equal the built-in parser keys, exactly."""
        from core.constants import REGISTERED_TYPES
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=MagicMock())
        builtin = set(registry.list_registered_types())

        # newsnow is a registry-level extension not exposed as a SourceType,
        # so compare on the SourceType-defined subset only.
        from core.constants import SourceType

        source_type_values = {member.value for member in SourceType}
        builtin_source_types = builtin & source_type_values

        assert builtin_source_types == set(REGISTERED_TYPES), (
            "REGISTERED_TYPES is out of sync with SourceRegistry. "
            f"declared={sorted(REGISTERED_TYPES)} "
            f"registered={sorted(builtin_source_types)}"
        )

    def test_every_registered_type_has_a_parser(self):
        """Each REGISTERED_TYPES member must resolve to an actual parser."""
        from core.constants import REGISTERED_TYPES
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=MagicMock())

        for source_type in REGISTERED_TYPES:
            assert registry.get_parser(source_type) is not None, source_type

    def test_unimplemented_types_are_not_declared_registered(self):
        """twitter/telegram/api have no parser and must not be advertised.

        They stay in SourceType for forward compatibility (and because stored
        rows may reference them), but they must not appear in
        REGISTERED_TYPES — that set is what the source API accepts.
        """
        from core.constants import REGISTERED_TYPES

        for unimplemented in ("twitter", "telegram", "api"):
            assert unimplemented not in REGISTERED_TYPES

    def test_wechat_is_absent_because_it_is_served_by_rss(self):
        """wechat has no dedicated parser; WeChat ingestion goes through RSS."""
        from core.constants import REGISTERED_TYPES

        assert "wechat" not in REGISTERED_TYPES


class TestSourceRegistryRegisterParser:
    """Tests for register_parser()."""

    @pytest.fixture
    def registry(self):
        """Create SourceRegistry instance."""
        from modules.ingestion.parsing.registry import SourceRegistry

        return SourceRegistry(fetcher=MagicMock())

    def test_register_parser_adds_parser(self, registry):
        """Test register_parser adds parser."""
        mock_parser = MagicMock()

        registry.register_parser("custom", mock_parser)

        assert registry.get_parser("custom") is mock_parser

    def test_register_parser_with_metadata(self, registry):
        """Test register_parser stores metadata."""
        from modules.ingestion.parsing.plugin import PluginMetadata

        mock_parser = MagicMock()
        metadata = PluginMetadata(
            name="custom_plugin",
            version="1.0.0",
            description="Custom parser",
            supported_types=["custom"],
            capabilities=[],
        )

        registry.register_parser("custom", mock_parser, metadata)

        assert registry.get_parser_metadata("custom") is metadata


class TestSourceRegistryRegisterParserClass:
    """Tests for register_parser_class()."""

    @pytest.fixture
    def registry(self):
        """Create SourceRegistry instance."""
        from modules.ingestion.parsing.registry import SourceRegistry

        return SourceRegistry(fetcher=MagicMock())

    def test_register_parser_class_instantiates_with_fetcher(self, registry):
        """Test register_parser_class instantiates with fetcher."""
        from modules.ingestion.parsing.base import BaseSourceParser

        mock_parser = MagicMock(spec=BaseSourceParser)
        MockParserClass = MagicMock(return_value=mock_parser)

        registry.register_parser_class("custom_class", MockParserClass)

        MockParserClass.assert_called_once_with(registry._fetcher)
        assert registry.get_parser("custom_class") is mock_parser


class TestSourceRegistrySourceManagement:
    """Tests for source management methods."""

    @pytest.fixture
    def registry(self):
        """Create SourceRegistry instance."""
        from modules.ingestion.parsing.registry import SourceRegistry

        return SourceRegistry(fetcher=MagicMock())

    def test_add_source(self, registry):
        """Test add_source registers source."""
        from modules.ingestion.domain.models import SourceConfig

        config = SourceConfig(
            id="source-1",
            name="Test Source",
            source_type="rss",
            url="https://example.com/feed",
            interval_minutes=30,
        )

        registry.add_source(config)

        assert registry.get_source("source-1") is config

    def test_remove_source(self, registry):
        """Test remove_source removes source."""
        from modules.ingestion.domain.models import SourceConfig

        config = SourceConfig(
            id="source-1",
            name="Test Source",
            source_type="rss",
            url="https://example.com/feed",
            interval_minutes=30,
        )

        registry.add_source(config)
        registry.remove_source("source-1")

        assert registry.get_source("source-1") is None

    def test_list_sources_enabled_only(self, registry):
        """Test list_sources filters by enabled."""
        from modules.ingestion.domain.models import SourceConfig

        enabled_config = SourceConfig(
            id="source-1",
            name="Enabled Source",
            source_type="rss",
            url="https://example.com/feed",
            interval_minutes=30,
            enabled=True,
        )
        disabled_config = SourceConfig(
            id="source-2",
            name="Disabled Source",
            source_type="rss",
            url="https://example.com/feed2",
            interval_minutes=30,
            enabled=False,
        )

        registry.add_source(enabled_config)
        registry.add_source(disabled_config)

        sources = registry.list_sources(enabled_only=True)

        assert len(sources) == 1
        assert sources[0].id == "source-1"

    def test_list_sources_all(self, registry):
        """Test list_sources returns all when enabled_only=False."""
        from modules.ingestion.domain.models import SourceConfig

        enabled_config = SourceConfig(
            id="source-1",
            name="Enabled Source",
            source_type="rss",
            url="https://example.com/feed",
            interval_minutes=30,
            enabled=True,
        )
        disabled_config = SourceConfig(
            id="source-2",
            name="Disabled Source",
            source_type="rss",
            url="https://example.com/feed2",
            interval_minutes=30,
            enabled=False,
        )

        registry.add_source(enabled_config)
        registry.add_source(disabled_config)

        sources = registry.list_sources(enabled_only=False)

        assert len(sources) == 2


class TestSourceRegistryParserInfo:
    """Tests for parser info methods."""

    @pytest.fixture
    def registry(self):
        """Create SourceRegistry instance."""
        from modules.ingestion.parsing.registry import SourceRegistry

        return SourceRegistry(fetcher=MagicMock())

    def test_list_registered_types(self, registry):
        """Test list_registered_types returns all types."""
        types = registry.list_registered_types()

        assert "rss" in types
        assert "newsnow" in types

    def test_list_parser_info(self, registry):
        """Test list_parser_info returns parser details."""
        info = registry.list_parser_info()

        assert len(info) >= 2  # rss and newsnow

        rss_info = next((i for i in info if i["source_type"] == "rss"), None)
        assert rss_info is not None
        assert rss_info["class_name"] == "RSSParser"
        assert rss_info["metadata"] is not None


class TestSourceRegistryClose:
    """Tests for close()."""

    @pytest.fixture
    def registry(self):
        """Create SourceRegistry instance."""
        from modules.ingestion.parsing.registry import SourceRegistry

        return SourceRegistry(fetcher=MagicMock())

    @pytest.mark.asyncio
    async def test_close_calls_parser_close(self, registry):
        """Test close() calls close on parsers with close method."""
        mock_parser = MagicMock()
        mock_parser.close = AsyncMock()

        registry.register_parser("custom", mock_parser)

        await registry.close()

        mock_parser.close.assert_called_once()


class TestT008LowFixes:
    """Regression tests for LOW findings."""

    @pytest.fixture
    def registry(self):
        """Create SourceRegistry instance."""
        from modules.ingestion.parsing.registry import SourceRegistry

        return SourceRegistry(fetcher=MagicMock())

    @pytest.mark.asyncio
    async def test_close_continues_after_a_parser_fails(self, registry):
        """#179: a raising parser must not stop the remaining parsers."""
        failing = MagicMock()
        failing.close = AsyncMock(side_effect=RuntimeError("close boom"))
        healthy = MagicMock()
        healthy.close = AsyncMock()

        registry.register_parser("failing", failing)
        registry.register_parser("healthy", healthy)

        await registry.close()

        failing.close.assert_awaited_once()
        healthy.close.assert_awaited_once()


class TestSourceRegistryLoadPlugins:
    """Tests for load_plugins() registration path.

    Regression: discovered plugins were only logged, never instantiated or
    registered into _parsers, so plugin parsers were unusable via get_parser.
    """

    @pytest.fixture
    def isolated_plugin_registry(self):
        """Snapshot and clear the global plugin registry for isolation."""
        from modules.ingestion.parsing import plugin

        saved = dict(plugin._plugin_registry)
        plugin._plugin_registry.clear()
        yield plugin._plugin_registry
        plugin._plugin_registry.clear()
        plugin._plugin_registry.update(saved)

    def _register_plugin_class(self, name: str, source_type: str, fail_init: bool = False):
        from modules.ingestion.domain.models import SourceConfig
        from modules.ingestion.parsing.base import BaseSourceParser
        from modules.ingestion.parsing.plugin import PluginMetadata, source_parser_plugin

        class _FakeParser(BaseSourceParser):
            def __init__(self, fetcher):
                if fail_init:
                    raise RuntimeError("boom")
                self.fetcher = fetcher

            async def parse(self, config: SourceConfig, force: bool = False):
                return []

        metadata = PluginMetadata(
            name=name,
            version="1.0.0",
            description="test plugin",
            supported_types=[source_type],
            capabilities=[],
        )
        # Decorator registers (class, metadata) into the global registry.
        wrapper = source_parser_plugin(name=name, supported_types=[source_type])
        registered_cls = wrapper(_FakeParser)
        return registered_cls, metadata

    def test_load_plugins_registers_discovered_parsers(self, tmp_path, isolated_plugin_registry):
        """Discovered plugin classes are instantiated with the fetcher and
        registered for every declared source type."""
        from modules.ingestion.parsing.plugin import get_registered_plugins
        from modules.ingestion.parsing.registry import SourceRegistry

        self._register_plugin_class("test_plugin", "custom_test_type")
        assert "test_plugin" in get_registered_plugins()

        mock_fetcher = MagicMock()
        registry = SourceRegistry(fetcher=mock_fetcher)
        loaded = registry.load_plugins([str(tmp_path)])  # empty scan dir

        assert "test_plugin" in loaded
        parser = registry.get_parser("custom_test_type")
        assert parser is not None
        assert parser.fetcher is mock_fetcher
        assert registry.get_parser_metadata("custom_test_type") is not None

    def test_load_plugins_skips_failing_plugin_without_blocking(
        self, tmp_path, isolated_plugin_registry
    ):
        """A plugin that fails to instantiate is skipped with a warning;
        remaining plugins still register."""
        from modules.ingestion.parsing.registry import SourceRegistry

        self._register_plugin_class("broken_plugin", "broken_type", fail_init=True)
        self._register_plugin_class("good_plugin", "good_type")

        registry = SourceRegistry(fetcher=MagicMock())
        loaded = registry.load_plugins([str(tmp_path)])

        assert "broken_plugin" in loaded  # discovered, though not usable
        assert registry.get_parser("broken_type") is None
        assert registry.get_parser("good_type") is not None

    def test_load_plugins_does_not_override_builtin_types(self, tmp_path, isolated_plugin_registry):
        """A plugin declaring an already-registered source type must not
        replace the built-in parser."""
        from modules.ingestion.parsing.plugin import PluginMetadata
        from modules.ingestion.parsing.registry import SourceRegistry

        # Register a plugin claiming the built-in "rss" type directly in the
        # global registry (bypassing the default-parser guard).
        class _RssHijacker:
            def __init__(self, fetcher):
                self.fetcher = fetcher

        from modules.ingestion.parsing import plugin as plugin_mod

        plugin_mod._plugin_registry["rss_hijacker"] = (
            _RssHijacker,
            PluginMetadata(
                name="rss_hijacker",
                version="1.0.0",
                description="tries to override rss",
                supported_types=["rss"],
                capabilities=[],
            ),
        )

        registry = SourceRegistry(fetcher=MagicMock())
        registry.load_plugins([str(tmp_path)])

        # Built-in RSSParser survives
        from modules.ingestion.parsing.rss_parser import RSSParser

        assert isinstance(registry.get_parser("rss"), RSSParser)


class TestT008LowFixes:
    """Regression tests for LOW findings."""

    def test_external_plugin_discovery_runs_once(self):
        """#256: no redundant discovery pass before scan_and_load_external_plugins."""
        from modules.ingestion.parsing import registry as registry_module
        from modules.ingestion.parsing.registry import SourceRegistry

        reg = SourceRegistry(fetcher=MagicMock())
        with (
            patch.object(registry_module, "scan_and_load_external_plugins") as mock_scan,
            patch.object(registry_module, "get_registered_plugins", return_value={}),
        ):
            reg.load_plugins(["/tmp/plugins"])

        mock_scan.assert_called_once_with(["/tmp/plugins"])

    @pytest.mark.asyncio
    async def test_close_continues_after_one_parser_fails(self):
        """#179: one failing close() must not stop the remaining parsers."""
        from modules.ingestion.parsing.registry import SourceRegistry

        reg = SourceRegistry(fetcher=MagicMock())
        bad = MagicMock()
        bad.close = AsyncMock(side_effect=RuntimeError("boom"))
        good = MagicMock()
        good.close = AsyncMock()
        reg.register_parser("bad", bad)
        reg.register_parser("good", good)

        await reg.close()

        good.close.assert_awaited_once()

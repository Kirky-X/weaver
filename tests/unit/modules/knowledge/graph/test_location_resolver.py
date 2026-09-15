# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for the ISO 3166 location resolver."""

from modules.knowledge.graph import location_resolver as location_resolver_module
from modules.knowledge.graph.location_resolver import LocationResolver


class TestLocationResolverInit:
    """Construction must stay cheap (#90)."""

    def test_does_not_load_unused_geonames_dataset(self) -> None:
        """#90: the geonames country dataset was never read — don't load it."""
        resolver = LocationResolver()

        assert not hasattr(resolver, "_country_data")
        assert not hasattr(resolver, "_gc")

    def test_module_does_not_import_geonamescache(self) -> None:
        """#90: the module must not pull in geonamescache again."""
        assert not hasattr(location_resolver_module, "GeonamesCache")


class TestNormalizeMemoization:
    """``normalize`` is pure, so repeated lookups must be served from cache (#69)."""

    def test_repeated_normalize_returns_cached_result(self) -> None:
        resolver = LocationResolver()

        first = resolver.normalize("中国")
        second = resolver.normalize("中国")

        assert first == second
        assert resolver._normalize_cache["中国"] is first

    def test_fuzzy_path_is_only_computed_once(self) -> None:
        """The second lookup must not re-run the rapidfuzz search."""
        resolver = LocationResolver()
        calls = 0
        original = resolver._normalize_uncached

        def counting(name: str):
            nonlocal calls
            calls += 1
            return original(name)

        resolver._normalize_uncached = counting

        resolver.normalize("北京市朝阳区")
        resolver.normalize("北京市朝阳区")

        assert calls == 1

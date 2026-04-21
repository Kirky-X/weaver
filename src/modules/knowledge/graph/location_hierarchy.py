# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Location hierarchy management using geonamescache.

Provides continent/country/province/city hierarchy tree
and geographic relationship queries.
"""

from __future__ import annotations

from dataclasses import dataclass

from geonamescache import GeonamesCache

from core.observability.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class LocationNode:
    """A node in the location hierarchy tree."""

    name: str
    iso_code: str | None
    level: str  # continent/country/province/city
    parent_code: str | None


class LocationHierarchy:
    """Manage location hierarchy relationships.

    Uses geonamescache for comprehensive geographic data.
    """

    def __init__(self) -> None:
        """Initialize location hierarchy with country data."""
        self._gc = GeonamesCache()
        self._country_data = self._gc.get_countries()
        log.debug(
            "LocationHierarchy initialized with {} countries",
            len(self._country_data),
        )

    def get_continent(self, iso_code: str) -> str | None:
        """Get the continent for a country.

        Args:
            iso_code: ISO 3166 alpha-2 country code.

        Returns:
            Continent name or None if not found.
        """
        country = self._country_data.get(iso_code)
        if country:
            return country.get("continent")
        return None

    def get_subdivisions(self, iso_code: str) -> list[dict]:
        """Get administrative subdivisions for a country.

        Args:
            iso_code: ISO 3166 alpha-2 country code.

        Returns:
            List of subdivision dictionaries.
        """
        # Simplified version - can be extended with geonamescache US states data
        return []

    def build_hierarchy_tree(self) -> dict:
        """Build complete hierarchy tree organized by continent.

        Returns:
            Dictionary with continents as keys and country lists as values.
        """
        tree: dict[str, list[dict]] = {}
        for iso_code, country in self._country_data.items():
            continent = country.get("continent", "Unknown")
            if continent not in tree:
                tree[continent] = []
            tree[continent].append(
                {
                    "name": country["name"],
                    "iso_code": iso_code,
                }
            )
        return tree

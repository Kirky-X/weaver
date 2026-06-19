# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Location name resolver using ISO 3166 standards.

Provides canonical name normalization and ISO code mapping
for country/region names in multiple languages.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pycountry
from geonamescache import GeonamesCache
from rapidfuzz import fuzz, process

from core.observability import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class LocationResult:
    """Result of location name normalization."""

    canonical_name: str
    iso_alpha2: str | None
    iso_alpha3: str | None
    confidence: float
    metadata: dict = field(default_factory=dict)


class LocationResolver:
    """Resolve and normalize location names to ISO 3166 standard.

    Uses pycountry and geonamescache for comprehensive coverage,
    with rapidfuzz for fuzzy matching fallback.
    """

    def __init__(self) -> None:
        """Initialize location resolver with multilingual index."""
        self._countries = pycountry.countries
        self._gc = GeonamesCache()
        self._country_data = self._gc.get_countries()
        self._name_to_iso: dict[str, str] = {}
        self._build_multilingual_index()

    def _build_multilingual_index(self) -> None:
        """Build multilingual name to ISO code mapping."""
        # Load English names from pycountry
        for country in self._countries:
            self._name_to_iso[country.name.lower()] = country.alpha_2
            if hasattr(country, "official_name"):
                self._name_to_iso[country.official_name.lower()] = country.alpha_2

        # Add common Chinese name mappings (Simplified and Traditional)
        chinese_names = {
            # Simplified Chinese
            "中国": "CN",
            "中国大陆": "CN",
            "中华人民共和国": "CN",
            "美国": "US",
            "美国本土": "US",
            "美利坚合众国": "US",
            "英国": "GB",
            "大不列颠": "GB",
            "联合王国": "GB",
            "日本": "JP",
            "韩国": "KR",
            "朝鲜": "KP",
            "俄罗斯": "RU",
            "法国": "FR",
            "德国": "DE",
            "印度": "IN",
            "巴西": "BR",
            "加拿大": "CA",
            "澳大利亚": "AU",
            "意大利": "IT",
            "西班牙": "ES",
            # Traditional Chinese
            "中國": "CN",
            "中國大陸": "CN",
            "中華人民共和國": "CN",
            "美國": "US",
            "英國": "GB",
            "韓國": "KR",
            "朝鮮": "KP",
            "俄羅斯": "RU",
            "法國": "FR",
            "德國": "DE",
            "澳大利亞": "AU",
        }
        self._name_to_iso.update(chinese_names)

        log.debug(
            "LocationResolver initialized with {} country mappings",
            len(self._name_to_iso),
        )

    def normalize(self, name: str) -> LocationResult:
        """Normalize a location name to canonical form.

        Args:
            name: Location name to normalize.

        Returns:
            LocationResult with canonical name and ISO codes.
        """
        # Exact match
        iso_code = self._name_to_iso.get(name.lower())
        if iso_code:
            country = pycountry.countries.get(alpha_2=iso_code)
            if country:
                return LocationResult(
                    canonical_name=country.name,
                    iso_alpha2=country.alpha_2,
                    iso_alpha3=country.alpha_3,
                    confidence=1.0,
                )

        # Fuzzy match using rapidfuzz
        matches = process.extract(
            name.lower(),
            self._name_to_iso.keys(),
            scorer=fuzz.ratio,
            limit=1,
        )
        if matches and matches[0][1] >= 85:
            iso_code = self._name_to_iso[matches[0][0]]
            country = pycountry.countries.get(alpha_2=iso_code)
            if country:
                return LocationResult(
                    canonical_name=country.name,
                    iso_alpha2=country.alpha_2,
                    iso_alpha3=country.alpha_3,
                    confidence=matches[0][1] / 100.0,
                )

        # No match found
        return LocationResult(
            canonical_name=name,
            iso_alpha2=None,
            iso_alpha3=None,
            confidence=0.0,
        )

    def find_name_by_iso(self, iso_code: str, predicate=None) -> str | None:
        """Find a name in the index matching the given ISO code.

        Args:
            iso_code: ISO 3166 alpha-2 country code.
            predicate: Optional callable to filter candidate names.

        Returns:
            First matching name, or None if not found.
        """
        for name, code in self._name_to_iso.items():
            if code == iso_code:
                if predicate is None or predicate(name):
                    return name
        return None

    def is_location(self, name: str) -> bool:
        """Check if a name is a known location.

        Args:
            name: Name to check.

        Returns:
            True if name is a known location.
        """
        return name.lower() in self._name_to_iso

    def get_hierarchy(self, iso_code: str) -> dict:
        """Get location hierarchy information.

        Args:
            iso_code: ISO 3166 alpha-2 country code.

        Returns:
            Dictionary with hierarchy information.
        """
        country = self._country_data.get(iso_code)
        if not country:
            return {}

        return {
            "name": country.get("name"),
            "iso_code": iso_code,
            "continent": country.get("continent"),
        }

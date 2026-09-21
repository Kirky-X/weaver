# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Unit tests for the built-in html/json index source manifest.

Guards against the two failure shapes documented in AGENTS.md: a manifest
entry whose source_type has no registered parser is created successfully but
silently never crawled, and a malformed entry fails only at seed time.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# scripts/ is not a package; put it on sys.path to import the manifest's
# single source of truth from pipeline.py directly.
_SCRIPTS_DIR = str(Path(__file__).parents[4] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from pipeline import INDEX_SOURCES, build_index_source_config

from modules.ingestion.domain.models import SourceConfig as SourceConfigModel
from modules.ingestion.parsing.document_parsers import (
    HTMLIndexParser,
    JSONApiParser,
)
from modules.ingestion.parsing.registry import SourceRegistry


class TestIndexSourcesManifest:
    """Structural invariants of the INDEX_SOURCES manifest."""

    def test_manifest_is_not_empty(self):
        assert len(INDEX_SOURCES) >= 30

    def test_ids_are_unique(self):
        ids = [entry["id"] for entry in INDEX_SOURCES]
        assert len(ids) == len(set(ids)), "duplicate source ids in manifest"

    def test_ids_match_source_type_prefix(self):
        """html-*/json- prefixes keep the id self-describing."""
        for entry in INDEX_SOURCES:
            assert entry["id"].startswith(entry["source_type"] + "-"), entry

    def test_source_types_are_crawlable(self):
        """Only types with a registered parser may appear in the manifest."""
        registry = SourceRegistry(fetcher=MagicMock())
        registered = set(registry.list_registered_types())
        for entry in INDEX_SOURCES:
            assert entry["source_type"] in registered, (
                f"{entry['id']}: source_type {entry['source_type']!r} has no "
                "parser — the source would be created but never crawled"
            )

    def test_urls_are_https_with_public_hosts(self):
        for entry in INDEX_SOURCES:
            url = entry["url"]
            assert url.startswith("https://"), entry["id"]
            host = url.split("/", 3)[2]
            assert "localhost" not in host and "127.0.0.1" not in host, entry["id"]

    def test_names_are_non_empty(self):
        for entry in INDEX_SOURCES:
            assert entry["name"].strip(), entry["id"]

    @pytest.mark.parametrize(
        "source_type,parser_cls",
        [("html", HTMLIndexParser), ("json", JSONApiParser)],
    )
    def test_every_manifest_type_resolves_to_its_parser(self, source_type, parser_cls):
        registry = SourceRegistry(fetcher=MagicMock())
        assert isinstance(registry.get_parser(source_type), parser_cls)


class TestIndexSourceConfigBuilding:
    """build_index_source_config output must satisfy SourceConfigModel."""

    def test_defaults_fill_shared_fields(self):
        entry = INDEX_SOURCES[0]
        config = build_index_source_config(entry)
        assert config["enabled"] is True
        assert config["interval_minutes"] == 30
        assert config["credibility"] == 0.70
        assert config["tier"] == 2
        assert config["id"] == entry["id"]
        assert config["url"] == entry["url"]

    @pytest.mark.parametrize("entry", INDEX_SOURCES, ids=lambda e: e["id"])
    def test_every_entry_builds_a_valid_source_config(self, entry):
        config = SourceConfigModel(**build_index_source_config(entry))
        assert config.id == entry["id"]
        assert config.url == entry["url"]
        assert config.source_type == entry["source_type"]


class TestManifestDocumentation:
    """AGENTS.md documents the manifest; its counts must not drift."""

    def test_agents_md_counts_match_manifest(self):
        agents_md = Path(__file__).parents[4].joinpath("AGENTS.md").read_text(encoding="utf-8")
        html_count = sum(1 for e in INDEX_SOURCES if e["source_type"] == "html")
        json_count = len(INDEX_SOURCES) - html_count
        assert (
            f"INDEX_SOURCES` — {len(INDEX_SOURCES)} 个内置源（html {html_count} + json {json_count}）"
            in agents_md
        )

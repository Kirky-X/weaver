# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Live availability tests for the built-in html/json index sources.

Each INDEX_SOURCES entry is fetched over the real network and pushed through
its real parser (HTMLIndexParser / JSONApiParser); a source must yield at
least one item. This is the pytest counterpart of the manual
``pipeline.py test --mode index`` run — no server, no database.

Run (from the project root):

    uv run pytest tests/integration/modules/ingestion/test_index_sources_live.py \
        -c tests/integration/pytest.ini --no-cov

``--no-cov``: the integration coverage gate is scoped to ``src/api`` and
these tests exercise ``scripts/`` + ``src/modules`` only, so the gate would
fail spuriously (same constraint as the e2e suite).

External services: the 30 public news endpoints in INDEX_SOURCES. Requires
outbound internet access; site-side anti-bot changes can fail individual
sources (that failing is exactly what this suite is for).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SCRIPTS_DIR = str(Path(__file__).parents[4] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from pipeline import INDEX_SOURCES, build_index_source_config

from modules.ingestion.domain.models import NewsItem, SourceConfig as SourceConfigModel
from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher
from modules.ingestion.parsing.registry import SourceRegistry

# Browser UAs: several of these sites return 403 to bare client UAs, and the
# production fetcher rotates a browser pool too.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
]

FETCH_TIMEOUT = 30.0
# One retry: gov.cn occasionally resets connections (empty-message
# TransportError); a single transient failure should not fail the source.
MAX_ATTEMPTS = 2


@pytest.fixture(scope="module")
async def fetcher() -> HttpxFetcher:
    f = HttpxFetcher(timeout=FETCH_TIMEOUT, user_agents=USER_AGENTS)
    yield f
    await f.close()


@pytest.fixture(scope="module")
def registry(fetcher: HttpxFetcher) -> SourceRegistry:
    return SourceRegistry(fetcher=fetcher)


async def _parse_with_retry(
    registry: SourceRegistry,
    config: SourceConfigModel,
) -> list[NewsItem]:
    """Parse a source, tolerating one transient network failure."""
    parser = registry.get_parser(config.source_type)
    assert parser is not None, f"no parser for {config.source_type}"

    last_error: Exception | None = None
    for _ in range(MAX_ATTEMPTS):
        try:
            return await parser.parse(config)
        except Exception as exc:
            last_error = exc
    raise AssertionError(
        f"{config.id}: {MAX_ATTEMPTS} attempts failed ({config.url})"
    ) from last_error


@pytest.mark.integration
class TestBuiltinIndexSourcesLive:
    """Every manifest source must yield at least one item over the network."""

    @pytest.mark.parametrize("entry", INDEX_SOURCES, ids=lambda e: e["id"])
    async def test_source_yields_items(self, registry: SourceRegistry, entry: dict):
        config = SourceConfigModel(**build_index_source_config(entry))
        items = await _parse_with_retry(registry, config)

        assert items, (
            f"{entry['id']} yielded 0 items from {entry['url']} — "
            "the endpoint may have moved (xinhua ds_<hash>.json filenames are "
            "site-generated) or the parser no longer matches its payload shape"
        )
        for item in items[:5]:
            assert item.url.startswith("http"), item.url

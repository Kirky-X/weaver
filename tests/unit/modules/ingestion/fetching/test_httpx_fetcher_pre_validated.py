# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""RED test for HttpxFetcher.fetch(pre_validated=...) — D3 dead code fix.

When the caller (SmartFetcher) has already validated the URL upstream,
HttpxFetcher must skip the redundant ``url_validator.validate`` call to
avoid double SSRF check + double URLhaus/PhishTank network round-trip.

See ``temp/report.md`` D3 (HttpxFetcher.fetch 双重校验) and specmark
change ``fix-pipeline-deadcode-perf`` T008-T009.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_pre_validated_skips_url_validator() -> None:
    """When pre_validated=True, url_validator.validate must not be called."""
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

    fetcher = HttpxFetcher()
    mock_validator = MagicMock()
    mock_validator.validate = AsyncMock()
    fetcher._url_validator = mock_validator

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html>ok</html>"
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.history = []
    mock_response.http_version = "HTTP/2"

    with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_response

        await fetcher.fetch("https://example.com", pre_validated=True)

    mock_validator.validate.assert_not_called()


@pytest.mark.asyncio
async def test_default_still_validates_url() -> None:
    """Regression guard: default behavior (pre_validated=False) still validates."""
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

    fetcher = HttpxFetcher()
    mock_validator = MagicMock()
    mock_validator.validate = AsyncMock()
    fetcher._url_validator = mock_validator

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html>ok</html>"
    mock_response.headers = {}
    mock_response.history = []
    mock_response.http_version = "HTTP/2"

    with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_response

        await fetcher.fetch("https://example.com")

    mock_validator.validate.assert_called_once_with("https://example.com")

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""RED test for HttpxFetcher User-Agent pool — P1-4 fix.

When ``user_agents`` list has multiple items, each request must carry
a ``User-Agent`` header drawn from the pool. This defeats naive
rate-limiter fingerprinting that blocks a single UA after N requests.

See ``temp/report.md`` P1-4 (单一 User-Agent) and specmark change
``fix-pipeline-deadcode-perf`` T026-T027.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_random_ua_selected_from_pool() -> None:
    """When user_agents has 3 items, request User-Agent must be one of them."""
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

    ua_pool = ["Mozilla/5.0 UA-A", "Mozilla/5.0 UA-B", "Mozilla/5.0 UA-C"]
    fetcher = HttpxFetcher(user_agents=ua_pool)

    captured_headers: list[dict[str, str]] = []

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html>ok</html>"
    mock_response.headers = {}
    mock_response.history = []
    mock_response.http_version = "HTTP/2"

    def _capture_send(request, *args, **kwargs):  # type: ignore[no-untyped-def]
        # Capture the request headers actually sent on the wire
        captured_headers.append(dict(request.headers))
        return mock_response

    with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = _capture_send
        # Issue 10 requests; each must draw UA from pool
        for _ in range(10):
            await fetcher.fetch("https://example.com")

    assert len(captured_headers) == 10, f"Expected 10 captures, got {len(captured_headers)}"
    used_uas = {h.get("user-agent") or h.get("User-Agent") for h in captured_headers}
    assert used_uas.issubset(
        set(ua_pool)
    ), f"All UAs must come from pool; got {used_uas}, pool={set(ua_pool)}"
    # Sanity: with 10 draws from 3 UAs, at least 2 distinct should appear
    # (probabilistic guarantee: P(all 10 same) = 3*(1/3)^10 ≈ 5e-5)
    assert (
        len(used_uas) >= 2
    ), f"Expected UA rotation; got only {len(used_uas)} distinct in 10 draws"


@pytest.mark.asyncio
async def test_default_single_ua_still_works() -> None:
    """Regression guard: without user_agents param, default UA is used."""
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

    fetcher = HttpxFetcher()  # No user_agents — backward compat
    captured_headers: list[dict[str, str]] = []

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html>ok</html>"
    mock_response.headers = {}
    mock_response.history = []
    mock_response.http_version = "HTTP/2"

    def _capture_send(request, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured_headers.append(dict(request.headers))
        return mock_response

    with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = _capture_send
        await fetcher.fetch("https://example.com")

    assert len(captured_headers) == 1
    ua = captured_headers[0].get("user-agent") or captured_headers[0].get("User-Agent")
    assert ua is not None, "Default UA must be set"
    assert "NewsBot" in ua, f"Default UA should contain NewsBot; got {ua!r}"


@pytest.mark.asyncio
async def test_explicit_headers_override_pool_ua() -> None:
    """Caller-supplied User-Agent header must override pool selection.

    Per ``_get_headers`` contract: ``{"User-Agent": random.choice(...), **(headers or {})}``
    — caller headers win. This lets per-request overrides (e.g. site-specific UA)
    coexist with the pool.
    """
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

    ua_pool = ["UA-A", "UA-B", "UA-C"]
    fetcher = HttpxFetcher(user_agents=ua_pool)

    captured_headers: list[dict[str, str]] = []

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html>ok</html>"
    mock_response.headers = {}
    mock_response.history = []
    mock_response.http_version = "HTTP/2"

    def _capture_send(request, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured_headers.append(dict(request.headers))
        return mock_response

    with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = _capture_send
        await fetcher.fetch(
            "https://example.com",
            headers={"User-Agent": "Caller-Override/1.0"},
        )

    assert len(captured_headers) == 1
    ua = captured_headers[0].get("user-agent") or captured_headers[0].get("User-Agent")
    assert ua == "Caller-Override/1.0", f"Caller UA must override pool; got {ua!r}"

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""RED test for HttpxFetcher 429/503 Retry-After handling — P1-4 fix.

When a server returns 429 (Too Many Requests) or 503 (Service
Unavailable) with a ``Retry-After`` header, the fetcher must:

1. Parse the header as a float (seconds).
2. Cap the wait at 60 seconds to prevent malicious servers from
   stalling the crawler indefinitely.
3. ``await asyncio.sleep(wait)`` before re-raising so the caller's
   retry loop resumes with a respectful delay.
4. Re-raise the original ``HTTPStatusError`` so the existing
   ``retry_network`` machinery handles subsequent retries.

See ``temp/report.md`` P1-4 (无 Retry-After 识别) and specmark change
``fix-pipeline-deadcode-perf`` T028-T029.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


def _make_status_error(
    status_code: int,
    headers: dict[str, str] | None = None,
) -> httpx.HTTPStatusError:
    """Build a real httpx.HTTPStatusError with the given status + headers."""
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(
        status_code=status_code,
        headers=headers or {},
        request=request,
    )
    return httpx.HTTPStatusError(
        message=f"HTTP {status_code}",
        request=request,
        response=response,
    )


@pytest.mark.asyncio
async def test_429_with_retry_after_triggers_sleep() -> None:
    """429 + Retry-After: 5 → asyncio.sleep(5.0) called, then raises."""
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

    fetcher = HttpxFetcher()
    exc = _make_status_error(429, {"Retry-After": "5"})

    with (
        patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send,
        patch(
            "modules.ingestion.fetching.httpx_fetcher.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
    ):
        mock_send.side_effect = exc
        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch("https://example.com")

    mock_sleep.assert_awaited()
    slept_seconds = mock_sleep.await_args.args[0]
    assert slept_seconds == 5.0, f"Expected sleep(5.0); got sleep({slept_seconds})"


@pytest.mark.asyncio
async def test_503_with_retry_after_triggers_sleep() -> None:
    """503 + Retry-After: 3 → asyncio.sleep(3.0) called, then raises."""
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

    fetcher = HttpxFetcher()
    exc = _make_status_error(503, {"Retry-After": "3"})

    with (
        patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send,
        patch(
            "modules.ingestion.fetching.httpx_fetcher.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
    ):
        mock_send.side_effect = exc
        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch("https://example.com")

    mock_sleep.assert_awaited()
    slept_seconds = mock_sleep.await_args.args[0]
    assert slept_seconds == 3.0, f"Expected sleep(3.0); got sleep({slept_seconds})"


@pytest.mark.asyncio
async def test_retry_after_capped_at_60s() -> None:
    """Retry-After: 120 → asyncio.sleep(60.0) — cap prevents stalling."""
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

    fetcher = HttpxFetcher()
    exc = _make_status_error(429, {"Retry-After": "120"})

    with (
        patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send,
        patch(
            "modules.ingestion.fetching.httpx_fetcher.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
    ):
        mock_send.side_effect = exc
        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch("https://example.com")

    mock_sleep.assert_awaited()
    slept_seconds = mock_sleep.await_args.args[0]
    assert slept_seconds == 60.0, f"Expected cap at 60.0; got sleep({slept_seconds})"


@pytest.mark.asyncio
async def test_429_without_retry_after_no_sleep() -> None:
    """429 without Retry-After header → no asyncio.sleep, just raise."""
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

    fetcher = HttpxFetcher()
    exc = _make_status_error(429, {})

    with (
        patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send,
        patch(
            "modules.ingestion.fetching.httpx_fetcher.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
    ):
        mock_send.side_effect = exc
        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch("https://example.com")

    mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_500_server_error_no_sleep() -> None:
    """500 (not 429/503) → no Retry-After handling, falls through to retry.

    Regression guard: only 429/503 should trigger Retry-After sleep.
    5xx other than 503 must keep the original "let retry_network handle" path.
    """
    from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

    fetcher = HttpxFetcher()
    exc = _make_status_error(500, {"Retry-After": "5"})

    with (
        patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send,
        patch(
            "modules.ingestion.fetching.httpx_fetcher.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
    ):
        mock_send.side_effect = exc
        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch("https://example.com")

    mock_sleep.assert_not_awaited()

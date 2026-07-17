# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""RED test for Crawler + RetryQueue wiring — D4 dead code fix.

RetryQueue was implemented but never wired into Crawler, so failed
fetches were silently dropped instead of being re-queued for retry.

See ``temp/report.md`` D4 (RetryQueue 死信队列未接入) and specmark
change ``fix-pipeline-deadcode-perf`` T011-T012.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import NewsItem

# Long enough content to pass MIN_ARTICLE_LENGTH validation
LONG_CONTENT = (
    "This is extracted content that is long enough to pass the minimum "
    "article length validation threshold of 100 characters in the crawler."
)


@pytest.fixture
def sample_item() -> NewsItem:
    """Create sample NewsItem for testing."""
    return NewsItem(
        url="https://example.com/article1",
        title="Test Article",
        source="test_source",
        publish_time=datetime.now(UTC),
        description="Test description",
    )


@pytest.fixture
def mock_retry_queue() -> MagicMock:
    """Mock RetryQueue with async enqueue."""
    queue = MagicMock()
    queue.enqueue = AsyncMock()
    return queue


class TestCrawlerRetryQueueWiring:
    """Tests that Crawler enqueues failed fetches to RetryQueue."""

    @staticmethod
    def _enqueue_called_with(mock_queue: MagicMock, url: str, host: str, attempt: int = 0) -> bool:
        """Assert enqueue was called with given args at least once.

        crawl_one may re-fetch with force_browser=True when body is
        insufficient, which can trigger a second enqueue. We assert
        the expected call is *present* (not call_count == 1).
        """
        expected = (url, host)
        for call in mock_queue.enqueue.call_args_list:
            args, kwargs = call
            call_url = args[0] if len(args) >= 1 else kwargs.get("url")
            call_host = args[1] if len(args) >= 2 else kwargs.get("host")
            call_attempt = kwargs.get("attempt", args[2] if len(args) >= 3 else 0)
            if call_url == url and call_host == host and call_attempt == attempt:
                return True
        return False

    @pytest.mark.asyncio
    async def test_fetch_exception_enqueues_retry(
        self, sample_item: NewsItem, mock_retry_queue: MagicMock
    ) -> None:
        """When _fetcher.fetch raises, RetryQueue.enqueue must be called."""
        from modules.ingestion.crawling.crawler import Crawler

        mock_fetcher = AsyncMock()
        # fetch() raises — simulates network/transport error
        mock_fetcher.fetch = AsyncMock(side_effect=ConnectionError("network down"))

        crawler = Crawler(
            smart_fetcher=mock_fetcher,
            retry_queue=mock_retry_queue,
        )

        await crawler.crawl_batch([sample_item])

        assert self._enqueue_called_with(
            mock_retry_queue, "https://example.com/article1", "example.com"
        ), f"enqueue not called with expected args; calls={mock_retry_queue.enqueue.call_args_list}"

    @pytest.mark.asyncio
    async def test_http_error_status_enqueues_retry(
        self, sample_item: NewsItem, mock_retry_queue: MagicMock
    ) -> None:
        """When fetch returns status >= 400, RetryQueue.enqueue must be called."""
        from modules.ingestion.crawling.crawler import Crawler

        mock_fetcher = AsyncMock()
        # fetch() returns 503 — server error
        mock_fetcher.fetch = AsyncMock(return_value=(503, "<html>Service Unavailable</html>", {}))

        crawler = Crawler(
            smart_fetcher=mock_fetcher,
            retry_queue=mock_retry_queue,
        )

        await crawler.crawl_batch([sample_item])

        assert self._enqueue_called_with(
            mock_retry_queue, "https://example.com/article1", "example.com"
        ), f"enqueue not called with expected args; calls={mock_retry_queue.enqueue.call_args_list}"

    @pytest.mark.asyncio
    async def test_no_retry_queue_does_not_raise(self, sample_item: NewsItem) -> None:
        """Without retry_queue, Crawler must still work (backward compat)."""
        from modules.ingestion.crawling.crawler import Crawler

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(side_effect=ConnectionError("network down"))

        # retry_queue defaults to None — must not raise
        crawler = Crawler(smart_fetcher=mock_fetcher)

        results = await crawler.crawl_batch([sample_item])

        # Should return FetchError, not raise
        assert len(results) == 1

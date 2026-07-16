# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for LadybugWriter EventNode integration (spec: event-node-integration)."""

from __future__ import annotations

import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.ladybug.writer import LadybugWriter


def _make_state(
    article_id=None,
    title="Test Article",
    body="Article body content",
    category="科技",
    publish_time=None,
    entities=None,
):
    """Create a pipeline state dict for testing."""
    if article_id is None:
        article_id = str(uuid.uuid4())

    raw = MagicMock()
    raw.url = "https://example.com/test"
    raw.title = title
    raw.source_host = "example.com"
    raw.publish_time = publish_time

    state = {
        "article_id": article_id,
        "raw": raw,
        "cleaned": {"title": title, "body": body},
        "category": category,
        "score": 0.85,
        "entities": entities or [],
    }
    return state


class TestLadybugWriterEventNodeCreation:
    """Tests for EventNode creation in LadybugWriter._write_locked (spec scenarios)."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock LadybugPool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return pool

    @pytest.fixture
    def writer(self, mock_pool):
        """Create LadybugWriter instance."""
        return LadybugWriter(mock_pool)

    @pytest.mark.asyncio
    async def test_event_node_created_with_full_attributes(self, writer, mock_pool):
        """Scenario 1: EventNode created with id, content, event_type, name, event_time.

        Verifies that after Article node creation, an EventNode is created
        with content=title+body, event_type='news', name=title.
        """
        article_id = str(uuid.uuid4())
        state = _make_state(
            article_id=article_id,
            title="AI技术突破",
            body="人工智能领域取得重大进展",
            category="科技",
        )

        # Mock article_repo.find_article_by_id to return None (new article)
        writer._article_repo = MagicMock()
        writer._article_repo.find_article_by_id = AsyncMock(return_value=None)
        writer._article_repo.create_article = AsyncMock(return_value="article-uuid")

        writer._entity_repo = MagicMock()
        writer._entity_repo.merge_entity = AsyncMock(return_value="entity-uuid")
        writer._entity_repo.merge_mentions_relation = AsyncMock()

        await writer.write(state)

        # Check that execute_query was called for EventNode creation
        calls = mock_pool.execute_query.call_args_list
        # Find the EventNode creation call
        event_node_found = False
        for call in calls:
            query = call[0][0] if call[0] else ""
            if "EventNode" in query and ("MERGE" in query or "CREATE" in query):
                event_node_found = True
                params = call[0][1] if len(call[0]) > 1 else call[1] if call[1] else {}
                # Verify EventNode attributes
                assert params.get("event_type") == "news"
                assert params.get("name") == "AI技术突破"
                assert "AI技术突破" in params.get("content", "")
                assert "人工智能领域取得重大进展" in params.get("content", "")
                break

        assert event_node_found, "EventNode creation query not found"

    @pytest.mark.asyncio
    async def test_event_node_linked_to_article(self, writer, mock_pool):
        """Scenario 2: EventNode linked to Article via HAS_EVENT relationship.

        Verifies that after EventNode creation, a HAS_EVENT relationship
        is created from Article to EventNode.
        """
        article_id = str(uuid.uuid4())
        state = _make_state(article_id=article_id, title="Test Title")

        writer._article_repo = MagicMock()
        writer._article_repo.find_article_by_id = AsyncMock(return_value=None)
        writer._article_repo.create_article = AsyncMock(return_value="article-uuid")

        writer._entity_repo = MagicMock()
        writer._entity_repo.merge_entity = AsyncMock(return_value="entity-uuid")
        writer._entity_repo.merge_mentions_relation = AsyncMock()

        await writer.write(state)

        # Check that HAS_EVENT relationship was created
        calls = mock_pool.execute_query.call_args_list
        has_event_found = False
        for call in calls:
            query = call[0][0] if call[0] else ""
            if "HAS_EVENT" in query:
                has_event_found = True
                break

        assert has_event_found, "HAS_EVENT relationship creation query not found"

    @pytest.mark.asyncio
    async def test_event_node_idempotent_update(self, writer, mock_pool):
        """Scenario 3: EventNode creation is idempotent.

        When EventNode already exists (same id), the MERGE semantics
        should update the existing node rather than creating a duplicate.
        """
        article_id = str(uuid.uuid4())
        state = _make_state(article_id=article_id, title="Updated Title")

        writer._article_repo = MagicMock()
        writer._article_repo.find_article_by_id = AsyncMock(
            return_value={"id": "existing-article-id", "pg_id": article_id}
        )
        writer._article_repo.create_article = AsyncMock(return_value="existing-article-id")

        writer._entity_repo = MagicMock()
        writer._entity_repo.merge_entity = AsyncMock(return_value="entity-uuid")
        writer._entity_repo.merge_mentions_relation = AsyncMock()

        await writer.write(state)

        # Verify EventNode uses MERGE (not CREATE) for idempotency
        calls = mock_pool.execute_query.call_args_list
        event_node_found = False
        for call in calls:
            query = call[0][0] if call[0] else ""
            if "EventNode" in query and ("MERGE" in query or "SET" in query):
                event_node_found = True
                break

        assert event_node_found, "EventNode MERGE/SET query not found (idempotency check)"

    @pytest.mark.asyncio
    async def test_event_node_content_from_cleaned_data(self, writer, mock_pool):
        """Scenario: EventNode with content from cleaned data.

        EventNode.content = "title\n\nbody", EventNode.name = "title".
        """
        article_id = str(uuid.uuid4())
        state = _make_state(
            article_id=article_id,
            title="Breaking News",
            body="Full article content here",
        )

        writer._article_repo = MagicMock()
        writer._article_repo.find_article_by_id = AsyncMock(return_value=None)
        writer._article_repo.create_article = AsyncMock(return_value="article-uuid")

        writer._entity_repo = MagicMock()
        writer._entity_repo.merge_entity = AsyncMock(return_value="entity-uuid")
        writer._entity_repo.merge_mentions_relation = AsyncMock()

        await writer.write(state)

        calls = mock_pool.execute_query.call_args_list
        for call in calls:
            query = call[0][0] if call[0] else ""
            if "EventNode" in query:
                params = call[0][1] if len(call[0]) > 1 else call[1] if call[1] else {}
                content = params.get("content", "")
                assert "Breaking News" in content
                assert "Full article content here" in content
                assert params.get("name") == "Breaking News"
                break

    @pytest.mark.asyncio
    async def test_event_node_with_category_in_attributes(self, writer, mock_pool):
        """Scenario: EventNode with category in attributes.

        When state contains category, EventNode.attributes includes category.
        """
        article_id = str(uuid.uuid4())
        state = _make_state(
            article_id=article_id,
            title="Tech News",
            category="科技",
        )

        writer._article_repo = MagicMock()
        writer._article_repo.find_article_by_id = AsyncMock(return_value=None)
        writer._article_repo.create_article = AsyncMock(return_value="article-uuid")

        writer._entity_repo = MagicMock()
        writer._entity_repo.merge_entity = AsyncMock(return_value="entity-uuid")
        writer._entity_repo.merge_mentions_relation = AsyncMock()

        await writer.write(state)

        calls = mock_pool.execute_query.call_args_list
        for call in calls:
            query = call[0][0] if call[0] else ""
            if "EventNode" in query:
                params = call[0][1] if len(call[0]) > 1 else call[1] if call[1] else {}
                attributes_str = params.get("attributes", "{}")
                attributes = (
                    json.loads(attributes_str)
                    if isinstance(attributes_str, str)
                    else attributes_str
                )
                assert attributes.get("category") == "科技"
                break

    @pytest.mark.asyncio
    async def test_no_event_node_without_article_id(self, writer, mock_pool):
        """Edge case: no EventNode created when article_id is missing."""
        state = _make_state()
        del state["article_id"]

        await writer.write(state)

        # Should return empty list, no EventNode queries
        calls = mock_pool.execute_query.call_args_list
        for call in calls:
            query = call[0][0] if call[0] else ""
            assert "EventNode" not in query

    @pytest.mark.asyncio
    async def test_write_article_with_none_publish_time_writes_current_time(
        self, writer, mock_pool
    ):
        """Scenario: publish_time 为 None 时写入当前时间，不写入 0 (epoch 脏数据)。

        参考 OpenSpec change: temporal-search-time-filter-fix
        历史 bug: writer.py:140 写入 `publish_time or 0`，导致 event_time=0
        破坏 temporal 搜索的时间窗口过滤。
        """
        before = int(time.time())
        article_id = str(uuid.uuid4())
        state = _make_state(
            article_id=article_id,
            title="No Publish Time",
            body="Content",
            publish_time=None,
        )

        writer._article_repo = MagicMock()
        writer._article_repo.find_article_by_id = AsyncMock(return_value=None)
        writer._article_repo.create_article = AsyncMock(return_value="article-uuid")

        writer._entity_repo = MagicMock()
        writer._entity_repo.merge_entity = AsyncMock(return_value="entity-uuid")
        writer._entity_repo.merge_mentions_relation = AsyncMock()

        await writer.write(state)
        after = int(time.time())

        # Find EventNode creation call and verify event_time > 0
        calls = mock_pool.execute_query.call_args_list
        event_node_params = None
        for call in calls:
            query = call[0][0] if call[0] else ""
            if "EventNode" in query and "event_time" in query:
                event_node_params = call[0][1] if len(call[0]) > 1 else call[1]
                break

        assert event_node_params is not None, "EventNode creation query not found"
        event_time = event_node_params.get("event_time", 0)
        # event_time MUST NOT be 0 (the legacy bug we are fixing)
        assert event_time > 0, f"event_time must be > 0, got {event_time} (legacy bug)"
        # event_time MUST be within [before, after] (current time fallback)
        assert before <= event_time <= after, f"event_time {event_time} not in [{before}, {after}]"

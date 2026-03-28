# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for PendingSyncRepo module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from modules.storage.pending_sync_repo import PendingSyncRepo


class TestPendingSyncRepo:
    """Tests for PendingSyncRepo."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock PostgresPool."""
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        """Create PendingSyncRepo with mock pool."""
        return PendingSyncRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_upsert_inserts_new_record(self, repo, mock_pool):
        """Test upsert() inserts a new pending sync record."""
        article_id = uuid4()
        sync_type = "entity_relation"
        payload = {"entities": [], "relations": []}

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        # First call: no existing record
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        await repo.upsert(article_id, sync_type, payload)

        mock_pool.session.assert_called_once()
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_record(self, repo, mock_pool):
        """Test upsert() updates an existing pending sync record."""
        article_id = uuid4()
        sync_type = "entity_relation"
        payload = {"entities": [{"name": "Test"}], "relations": []}

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        # Existing record
        mock_existing = MagicMock()
        mock_existing.payload = {}
        mock_existing.retry_count = 2
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_existing
        mock_session.execute.return_value = mock_result

        await repo.upsert(article_id, sync_type, payload)

        assert mock_existing.payload == payload
        assert mock_existing.retry_count == 0
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_get_pending_returns_records(self, repo, mock_pool):
        """Test get_pending() returns pending sync records."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_records = [MagicMock(), MagicMock()]
        mock_result.scalars.return_value.all.return_value = mock_records
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        result = await repo.get_pending(limit=50)

        mock_pool.session.assert_called_once()
        assert result == mock_records

    @pytest.mark.asyncio
    async def test_mark_synced_updates_status(self, repo, mock_pool):
        """Test mark_synced() updates record status to synced."""
        record_id = 42

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.mark_synced(record_id)

        mock_pool.session.assert_called_once()
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_mark_failed_increments_retry_count(self, repo, mock_pool):
        """Test mark_failed() increments retry count."""
        record_id = 42
        error_msg = "Connection timeout"

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_record = MagicMock()
        mock_record.retry_count = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_session.execute.return_value = mock_result

        await repo.mark_failed(record_id, error_msg)

        assert mock_record.retry_count == 2
        assert mock_record.error == error_msg
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_mark_failed_sets_failed_status_after_5_retries(self, repo, mock_pool):
        """Test mark_failed() sets status to failed after 5 retries."""
        record_id = 42

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_record = MagicMock()
        mock_record.retry_count = 4  # Will become 5
        mock_record.status = "pending"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_session.execute.return_value = mock_result

        await repo.mark_failed(record_id, "Error")

        assert mock_record.retry_count == 5
        assert mock_record.status == "failed"

    @pytest.mark.asyncio
    async def test_cleanup_old_synced_deletes_old_records(self, repo, mock_pool):
        """Test cleanup_old_synced() deletes synced records older than cutoff."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 15
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_old_synced(days=7)

        mock_pool.session.assert_called_once()
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called()
        assert removed == 15

    def test_reconstruct_state_from_payload_full(self, repo):
        """Test reconstruct_state_from_payload() reconstructs complete state."""
        payload = {
            "article_id": "test-id",
            "raw": {"url": "https://example.com", "title": "Test"},
            "cleaned": {"title": "Cleaned", "body": "Body"},
            "category": "科技",
            "score": 0.85,
            "entities": [{"name": "Entity1"}],
            "relations": [{"source": "e1", "target": "e2"}],
            "merged_source_ids": ["id1", "id2"],
            "summary_info": {"summary": "Summary"},
            "sentiment": {"sentiment": "positive"},
            "credibility": {"score": 0.9},
            "prompt_versions": {"v1": "1.0"},
            "is_merged": True,
        }

        state = repo.reconstruct_state_from_payload(payload)

        assert state["article_id"] == "test-id"
        assert state["raw"] == payload["raw"]
        assert state["cleaned"] == payload["cleaned"]
        assert state["category"] == "科技"
        assert state["score"] == 0.85
        assert state["entities"] == payload["entities"]
        assert state["relations"] == payload["relations"]
        assert state["merged_source_ids"] == payload["merged_source_ids"]
        assert state["summary_info"] == payload["summary_info"]
        assert state["sentiment"] == payload["sentiment"]
        assert state["credibility"] == payload["credibility"]
        assert state["prompt_versions"] == payload["prompt_versions"]
        assert state["is_merged"] is True

    def test_reconstruct_state_from_payload_partial(self, repo):
        """Test reconstruct_state_from_payload() handles partial payload."""
        payload = {
            "entities": [{"name": "Entity1"}],
            "relations": [],
        }

        state = repo.reconstruct_state_from_payload(payload)

        assert state["entities"] == [{"name": "Entity1"}]
        assert state["relations"] == []
        assert "article_id" not in state
        assert "raw" not in state

    def test_reconstruct_state_from_payload_empty(self, repo):
        """Test reconstruct_state_from_payload() handles empty payload."""
        state = repo.reconstruct_state_from_payload({})

        assert state == {}

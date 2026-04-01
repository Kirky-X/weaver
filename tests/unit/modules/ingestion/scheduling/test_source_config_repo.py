# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for ingestion scheduling SourceConfigRepo."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import SourceConfig
from modules.ingestion.scheduling.source_config_repo import SourceConfigRepo


class TestSourceConfigRepoInit:
    """Tests for SourceConfigRepo initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_pool = MagicMock()
        repo = SourceConfigRepo(mock_pool)
        assert repo._pool is mock_pool


class TestSourceConfigRepoGet:
    """Tests for get method."""

    @pytest.mark.asyncio
    async def test_get_found(self):
        """Test get returns config when source exists."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "Test Source"
        mock_source.url = "https://example.com/feed.xml"
        mock_source.source_type = "rss"
        mock_source.enabled = True
        mock_source.interval_minutes = 60
        mock_source.per_host_concurrency = 2
        mock_source.credibility = 0.8
        mock_source.tier = 1
        mock_source.last_crawl_time = None
        mock_source.etag = None
        mock_source.last_modified = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_source
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        config = await repo.get("test-id")

        assert config is not None
        assert config.id == "test-id"
        assert config.name == "Test Source"

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        """Test get returns None when source not found."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        config = await repo.get("nonexistent")

        assert config is None


class TestSourceConfigRepoGetByUrl:
    """Tests for get_by_url method."""

    @pytest.mark.asyncio
    async def test_get_by_url_found(self):
        """Test get_by_url returns config when source exists."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "Test Source"
        mock_source.url = "https://example.com/feed.xml"
        mock_source.source_type = "rss"
        mock_source.enabled = True
        mock_source.interval_minutes = 60
        mock_source.per_host_concurrency = 2
        mock_source.credibility = 0.8
        mock_source.tier = 1
        mock_source.last_crawl_time = None
        mock_source.etag = None
        mock_source.last_modified = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_source
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        config = await repo.get_by_url("https://example.com/feed.xml")

        assert config is not None
        assert config.url == "https://example.com/feed.xml"

    @pytest.mark.asyncio
    async def test_get_by_url_not_found(self):
        """Test get_by_url returns None when source not found."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        config = await repo.get_by_url("https://nonexistent.com/feed.xml")

        assert config is None


class TestSourceConfigRepoGetCredibility:
    """Tests for get_credibility method."""

    @pytest.mark.asyncio
    async def test_get_credibility_found(self):
        """Test get_credibility returns score when found."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_source = MagicMock()
        mock_source.credibility = 0.85

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_source
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        credibility = await repo.get_credibility("example.com")

        assert credibility == 0.85

    @pytest.mark.asyncio
    async def test_get_credibility_not_found(self):
        """Test get_credibility returns None when not found."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        credibility = await repo.get_credibility("unknown.com")

        assert credibility is None

    @pytest.mark.asyncio
    async def test_get_credibility_null_value(self):
        """Test get_credibility returns None when credibility is null."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_source = MagicMock()
        mock_source.credibility = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_source
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        credibility = await repo.get_credibility("example.com")

        assert credibility is None


class TestSourceConfigRepoListSources:
    """Tests for list_sources method."""

    @pytest.mark.asyncio
    async def test_list_sources_all(self):
        """Test list_sources returns all sources when enabled_only=False."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_sources = []
        for i in range(3):
            source = MagicMock()
            source.id = f"source-{i}"
            source.name = f"Source {i}"
            source.url = f"https://example{i}.com/feed.xml"
            source.source_type = "rss"
            source.enabled = i % 2 == 0
            source.interval_minutes = 60
            source.per_host_concurrency = 2
            source.credibility = 0.8
            source.tier = 1
            source.last_crawl_time = None
            source.etag = None
            source.last_modified = None
            mock_sources.append(source)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_sources
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        configs = await repo.list_sources(enabled_only=False)

        assert len(configs) == 3

    @pytest.mark.asyncio
    async def test_list_sources_enabled_only(self):
        """Test list_sources filters by enabled."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        await repo.list_sources(enabled_only=True)

        assert mock_session.execute.called


class TestSourceConfigRepoUpsert:
    """Tests for upsert method."""

    @pytest.mark.asyncio
    async def test_upsert_new_source(self):
        """Test upsert creates new source."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        config = SourceConfig(
            id="new-source-id",
            name="New Source",
            url="https://newsource.com/feed.xml",
            source_type="rss",
            enabled=True,
            interval_minutes=60,
            per_host_concurrency=2,
            credibility=0.9,
            tier=1,
        )

        mock_source = MagicMock()
        mock_source.id = "new-source-id"
        mock_source.name = "New Source"
        mock_source.url = "https://newsource.com/feed.xml"
        mock_source.source_type = "rss"
        mock_source.enabled = True
        mock_source.interval_minutes = 60
        mock_source.per_host_concurrency = 2
        mock_source.credibility = 0.9
        mock_source.tier = 1
        mock_source.last_crawl_time = None
        mock_source.etag = None
        mock_source.last_modified = None

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_source
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        result = await repo.upsert(config)

        assert result.id == "new-source-id"
        assert mock_session.commit.called


class TestSourceConfigRepoDelete:
    """Tests for delete method."""

    @pytest.mark.asyncio
    async def test_delete_found(self):
        """Test delete returns True when source found and deleted."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_source = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_source
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        result = await repo.delete("test-id")

        assert result is True
        assert mock_session.delete.called
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """Test delete returns False when source not found."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = SourceConfigRepo(mock_pool)
        result = await repo.delete("nonexistent")

        assert result is False
        assert not mock_session.delete.called


class TestSourceConfigRepoUpdateCrawlState:
    """Tests for update_crawl_state method."""

    @pytest.mark.asyncio
    async def test_update_crawl_state_basic(self):
        """Test update_crawl_state with basic parameters."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        crawl_time = datetime.now(UTC)

        repo = SourceConfigRepo(mock_pool)
        await repo.update_crawl_state("test-id", crawl_time)

        assert mock_session.execute.called
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_update_crawl_state_with_etag(self):
        """Test update_crawl_state with etag."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        crawl_time = datetime.now(UTC)

        repo = SourceConfigRepo(mock_pool)
        await repo.update_crawl_state("test-id", crawl_time, etag='"abc123"')

        assert mock_session.execute.called
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_update_crawl_state_with_last_modified(self):
        """Test update_crawl_state with last_modified."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        crawl_time = datetime.now(UTC)

        repo = SourceConfigRepo(mock_pool)
        await repo.update_crawl_state(
            "test-id", crawl_time, last_modified="Mon, 01 Jan 2024 00:00:00 GMT"
        )

        assert mock_session.execute.called
        assert mock_session.commit.called


class TestSourceConfigRepoToConfig:
    """Tests for _to_config static method."""

    def test_to_config_basic(self):
        """Test _to_config converts source to config."""
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "Test Source"
        mock_source.url = "https://example.com/feed.xml"
        mock_source.source_type = "rss"
        mock_source.enabled = True
        mock_source.interval_minutes = 60
        mock_source.per_host_concurrency = 2
        mock_source.credibility = 0.8
        mock_source.tier = 1
        mock_source.last_crawl_time = None
        mock_source.etag = None
        mock_source.last_modified = None

        config = SourceConfigRepo._to_config(mock_source)

        assert config.id == "test-id"
        assert config.name == "Test Source"
        assert config.url == "https://example.com/feed.xml"
        assert config.source_type == "rss"
        assert config.enabled is True

    def test_to_config_null_credibility(self):
        """Test _to_config handles null credibility."""
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "Test Source"
        mock_source.url = "https://example.com/feed.xml"
        mock_source.source_type = "rss"
        mock_source.enabled = True
        mock_source.interval_minutes = 60
        mock_source.per_host_concurrency = 2
        mock_source.credibility = None
        mock_source.tier = 1
        mock_source.last_crawl_time = None
        mock_source.etag = None
        mock_source.last_modified = None

        config = SourceConfigRepo._to_config(mock_source)

        assert config.credibility is None

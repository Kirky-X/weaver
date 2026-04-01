# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for SourceAuthorityRepo."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.postgres.source_authority_repo import SourceAuthorityRepo


class TestSourceAuthorityRepoInit:
    """Tests for SourceAuthorityRepo initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_pool = MagicMock()
        repo = SourceAuthorityRepo(mock_pool)
        assert repo._pool is mock_pool


class TestGetOrCreate:
    """Tests for get_or_create method."""

    @pytest.mark.asyncio
    async def test_get_existing_authority(self):
        """Test getting existing authority."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_authority = MagicMock()
        mock_authority.host = "example.com"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_authority
        mock_session.execute.return_value = mock_result

        repo = SourceAuthorityRepo(mock_pool)
        result = await repo.get_or_create("example.com")

        assert result is mock_authority
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_new_authority(self):
        """Test creating new authority."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = SourceAuthorityRepo(mock_pool)
        result = await repo.get_or_create("newsource.com", auto_score=0.75)

        assert mock_session.add.called
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_create_with_auto_score(self):
        """Test creating authority with auto_score."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = SourceAuthorityRepo(mock_pool)
        await repo.get_or_create("scored.com", auto_score=0.85)

        # Verify session.add was called
        assert mock_session.add.called


class TestUpdateAuthority:
    """Tests for update_authority method."""

    @pytest.mark.asyncio
    async def test_update_authority_basic(self):
        """Test basic authority update."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        repo = SourceAuthorityRepo(mock_pool)
        await repo.update_authority("example.com", 0.9)

        assert mock_session.execute.called
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_update_authority_with_tier(self):
        """Test authority update with tier."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        repo = SourceAuthorityRepo(mock_pool)
        await repo.update_authority("example.com", 0.8, tier=1)

        assert mock_session.execute.called

    @pytest.mark.asyncio
    async def test_update_authority_needs_review(self):
        """Test authority update with needs_review flag."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        repo = SourceAuthorityRepo(mock_pool)
        await repo.update_authority("example.com", 0.7, needs_review=True)

        assert mock_session.commit.called


class TestGetNeedsReview:
    """Tests for get_needs_review method."""

    @pytest.mark.asyncio
    async def test_get_needs_review_found(self):
        """Test getting authorities needing review."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_authority = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_authority]
        mock_session.execute.return_value = mock_result

        repo = SourceAuthorityRepo(mock_pool)
        result = await repo.get_needs_review()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_needs_review_empty(self):
        """Test when no authorities need review."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        repo = SourceAuthorityRepo(mock_pool)
        result = await repo.get_needs_review()

        assert result == []


class TestListAll:
    """Tests for list_all method."""

    @pytest.mark.asyncio
    async def test_list_all_found(self):
        """Test listing all authorities."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_authorities = [MagicMock(host=f"source{i}.com") for i in range(3)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_authorities
        mock_session.execute.return_value = mock_result

        repo = SourceAuthorityRepo(mock_pool)
        result = await repo.list_all()

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_all_empty(self):
        """Test listing when no authorities exist."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        repo = SourceAuthorityRepo(mock_pool)
        result = await repo.list_all()

        assert result == []


class TestUpdateAutoScore:
    """Tests for update_auto_score method."""

    @pytest.mark.asyncio
    async def test_update_auto_score(self):
        """Test updating auto score."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        repo = SourceAuthorityRepo(mock_pool)
        await repo.update_auto_score("example.com", 0.88)

        assert mock_session.execute.called
        assert mock_session.commit.called

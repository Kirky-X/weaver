# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ArticleVersionRepo — article version history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from core.db.models import ArticleVersion
from tests.helpers import create_mock_relational_pool

# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────


def _make_version(
    article_id: uuid.UUID | None = None,
    version: int = 1,
    title: str = "Title v1",
    body: str = "Body v1",
    summary: str | None = None,
    category: str | None = None,
    score: float | None = None,
    changed_fields: list[str] | None = None,
) -> ArticleVersion:
    """Create an ArticleVersion instance for testing."""
    return ArticleVersion(
        article_id=article_id or uuid.uuid4(),
        version=version,
        title=title,
        body=body,
        summary=summary,
        category=category,
        score=score,
        changed_fields=changed_fields,
    )


# ────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────


class TestCreateVersionStoresSnapshot:
    """test_create_version_stores_snapshot — creates a version snapshot with changed_fields."""

    @pytest.mark.asyncio
    async def test_creates_version_with_changed_fields(self) -> None:
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        article_id = uuid.uuid4()
        pool = create_mock_relational_pool()
        session = pool.session.return_value

        # Mock: no existing versions → version 1
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        session.execute.return_value = scalar_result

        repo = ArticleVersionRepo(pool)

        result = await repo.create_version(
            article_id=article_id,
            title="Old Title",
            body="Old Body",
            summary="Old Summary",
            category="tech",
            score=0.85,
            changed_fields=["title", "body"],
        )

        # Verify session.add was called with an ArticleVersion
        session.add.assert_called_once()
        added_obj = session.add.call_args[0][0]
        assert isinstance(added_obj, ArticleVersion)
        assert added_obj.article_id == article_id
        assert added_obj.version == 1
        assert added_obj.title == "Old Title"
        assert added_obj.body == "Old Body"
        assert added_obj.summary == "Old Summary"
        assert added_obj.category == "tech"
        assert added_obj.score == 0.85
        assert added_obj.changed_fields == ["title", "body"]

    @pytest.mark.asyncio
    async def test_commits_after_create(self) -> None:
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        article_id = uuid.uuid4()
        pool = create_mock_relational_pool()
        session = pool.session.return_value
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        session.execute.return_value = scalar_result

        repo = ArticleVersionRepo(pool)

        await repo.create_version(
            article_id=article_id,
            title="T",
            body="B",
            summary=None,
            category=None,
            score=None,
            changed_fields=[],
        )

        session.commit.assert_called_once()


class TestGetVersionHistoryReturnsOrdered:
    """test_get_version_history_returns_ordered — returns versions ordered by version number desc."""

    @pytest.mark.asyncio
    async def test_returns_versions_newest_first(self) -> None:
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        article_id = uuid.uuid4()
        pool = create_mock_relational_pool()
        session = pool.session.return_value

        v1 = _make_version(article_id=article_id, version=1, title="v1")
        v2 = _make_version(article_id=article_id, version=2, title="v2")
        v3 = _make_version(article_id=article_id, version=3, title="v3")

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [v3, v2, v1]
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock

        repo = ArticleVersionRepo(pool)

        versions = await repo.get_version_history(article_id)

        assert len(versions) == 3
        assert versions[0].version == 3
        assert versions[1].version == 2
        assert versions[2].version == 1

    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        article_id = uuid.uuid4()
        pool = create_mock_relational_pool()
        session = pool.session.return_value

        v3 = _make_version(article_id=article_id, version=3, title="v3")

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [v3]
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock

        repo = ArticleVersionRepo(pool)

        versions = await repo.get_version_history(article_id, limit=1)

        assert len(versions) == 1
        assert versions[0].version == 3

    @pytest.mark.asyncio
    async def test_empty_history(self) -> None:
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        article_id = uuid.uuid4()
        pool = create_mock_relational_pool()
        session = pool.session.return_value

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock

        repo = ArticleVersionRepo(pool)

        versions = await repo.get_version_history(article_id)

        assert versions == []


class TestChangedFieldsTracking:
    """test_changed_fields_tracking — tracks which fields changed."""

    @pytest.mark.asyncio
    async def test_changed_fields_stored_in_version(self) -> None:
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        article_id = uuid.uuid4()
        pool = create_mock_relational_pool()
        session = pool.session.return_value
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        session.execute.return_value = scalar_result

        repo = ArticleVersionRepo(pool)

        await repo.create_version(
            article_id=article_id,
            title="Updated Title",
            body="Same Body",
            summary=None,
            category="politics",
            score=0.9,
            changed_fields=["title", "category", "score"],
        )

        added_obj = session.add.call_args[0][0]
        assert "title" in added_obj.changed_fields
        assert "category" in added_obj.changed_fields
        assert "score" in added_obj.changed_fields
        assert "body" not in added_obj.changed_fields

    @pytest.mark.asyncio
    async def test_no_changes_empty_list(self) -> None:
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        article_id = uuid.uuid4()
        pool = create_mock_relational_pool()
        session = pool.session.return_value
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        session.execute.return_value = scalar_result

        repo = ArticleVersionRepo(pool)

        await repo.create_version(
            article_id=article_id,
            title="Same",
            body="Same",
            summary=None,
            category=None,
            score=None,
            changed_fields=[],
        )

        added_obj = session.add.call_args[0][0]
        # Empty list is stored as None (nullable column, semantically equivalent)
        assert added_obj.changed_fields is None or added_obj.changed_fields == []


class TestVersionAutoIncrement:
    """test_version_auto_increment — version number auto-increments."""

    @pytest.mark.asyncio
    async def test_first_version_is_one(self) -> None:
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        article_id = uuid.uuid4()
        pool = create_mock_relational_pool()
        session = pool.session.return_value
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        session.execute.return_value = scalar_result

        repo = ArticleVersionRepo(pool)

        await repo.create_version(
            article_id=article_id,
            title="T",
            body="B",
            summary=None,
            category=None,
            score=None,
            changed_fields=["title"],
        )

        added_obj = session.add.call_args[0][0]
        assert added_obj.version == 1

    @pytest.mark.asyncio
    async def test_subsequent_version_increments(self) -> None:
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        article_id = uuid.uuid4()
        pool = create_mock_relational_pool()
        session = pool.session.return_value
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = 2  # existing max version
        session.execute.return_value = scalar_result

        repo = ArticleVersionRepo(pool)

        await repo.create_version(
            article_id=article_id,
            title="T",
            body="B",
            summary=None,
            category=None,
            score=None,
            changed_fields=["body"],
        )

        added_obj = session.add.call_args[0][0]
        assert added_obj.version == 3


class TestGetLatestVersion:
    """test_get_latest_version — returns the most recent version."""

    @pytest.mark.asyncio
    async def test_returns_latest_version(self) -> None:
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        article_id = uuid.uuid4()
        pool = create_mock_relational_pool()
        session = pool.session.return_value

        latest = _make_version(article_id=article_id, version=5, title="v5")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = latest
        session.execute.return_value = result_mock

        repo = ArticleVersionRepo(pool)

        result = await repo.get_latest_version(article_id)

        assert result is not None
        assert result.version == 5
        assert result.title == "v5"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_versions(self) -> None:
        from modules.storage.postgres.article_version_repo import ArticleVersionRepo

        article_id = uuid.uuid4()
        pool = create_mock_relational_pool()
        session = pool.session.return_value

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock

        repo = ArticleVersionRepo(pool)

        result = await repo.get_latest_version(article_id)

        assert result is None

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T004 RED: bulk_insert_raw batch insert for RawArticle.

Bug (P0-2):
    ``src/modules/ingestion/domain/processor.py:170-176`` calls
    ``insert_raw`` per-article in a for-loop, triggering N session
    round-trips and N commits per crawl batch. This is the second
    largest token/wall-time waste after D1.

Fix (T005-T006):
    Add ``bulk_insert_raw(articles, task_id=None) -> list[uuid.UUID]``
    to ``PostgresArticleRepository``:
    - Batch pre-query existing URLs via ``WHERE source_url = ANY(:urls)``
    - Single ``session.add_all`` + single ``session.commit()``
    - Fallback to per-article ``insert_raw`` on batch failure

This test asserts the three guarantees:
    1. 3 RawArticle inputs return 3 UUIDs (one per article)
    2. Single commit (not N commits)
    3. URLs already in articles_core are deduped (return existing id, skip insert)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import RawArticle


def _make_raw(url: str, title: str = "T", body: str = "B" * 250) -> RawArticle:
    return RawArticle(
        url=url,
        title=title,
        body=body,
        source="test",
        source_host="example.com",
        source_id="rss-test",
        publish_time=datetime(2026, 1, 1),
        description="",
    )


class _FakeResult:
    """Fake SQLAlchemy Result for SELECT queries."""

    def __init__(self, rows: list[tuple] | None = None, scalars: list | None = None):
        self._rows = rows or []
        self._scalars = scalars or []

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def all_scalars(self):
        return self._scalars

    def scalar_one_or_none(self):
        return self._scalars[0] if self._scalars else None


class _FakeSession:
    """Fake AsyncSession that records add_all / commit calls."""

    def __init__(self, existing_urls: dict[str, uuid.UUID] | None = None):
        self.existing_urls = existing_urls or {}
        self.added_objects: list[object] = []
        self.commit_count = 0
        self.flush_count = 0
        self.executed_queries: list[object] = []
        self._next_uuid = uuid.uuid4

    def add(self, obj):
        self.added_objects.append(obj)

    def add_all(self, objs):
        self.added_objects.extend(objs)

    async def flush(self):
        self.flush_count += 1
        # Assign IDs to newly added ArticleCore objects (mimic SQLAlchemy
        # server-side DEFAULT primary key assignment on flush)
        from core.db import ArticleCore

        for obj in self.added_objects:
            if isinstance(obj, ArticleCore) and obj.id is None:
                obj.id = self._next_uuid()

    async def commit(self):
        self.commit_count += 1
        # Also assign IDs on commit (in case any were added without flush)
        from core.db import ArticleCore

        for obj in self.added_objects:
            if isinstance(obj, ArticleCore) and obj.id is None:
                obj.id = self._next_uuid()

    async def execute(self, stmt):
        self.executed_queries.append(stmt)
        # Inspect compiled SQL to detect pre-query of existing URLs
        compiled = str(stmt)
        if "articles_core" in compiled and "source_url" in compiled:
            # Return rows of (source_url, id) for any URL in existing_urls
            rows = [(url, aid) for url, aid in self.existing_urls.items()]
            return _FakeResult(rows=rows)
        # Fallback: empty result
        return _FakeResult(rows=[], scalars=[])


class _FakePool:
    """Fake RelationalPool returning _FakeSession via async context manager."""

    def __init__(self, session: _FakeSession):
        self._session = session

    def session(self):
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=self._session)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm


@pytest.mark.asyncio
async def test_bulk_insert_raw_batch_inserts_articles() -> None:
    """3 RawArticle inputs → 3 UUIDs, single commit, URLs deduped."""
    from modules.storage.postgres.article_repo import ArticleRepo

    # 1 of the 3 URLs already exists (dedup check)
    existing_id = uuid.uuid4()
    existing_url = "https://example.com/existing"
    fake_session = _FakeSession(
        existing_urls={existing_url: existing_id},
    )
    repo = ArticleRepo(pool=_FakePool(fake_session))

    articles = [
        _make_raw(existing_url, title="Existing"),
        _make_raw("https://example.com/new1", title="New1"),
        _make_raw("https://example.com/new2", title="New2"),
    ]

    result = await repo.bulk_insert_raw(articles)

    # 3 UUIDs returned (one existing + two new)
    assert len(result) == 3, f"Expected 3 UUIDs, got {len(result)}"
    assert existing_id in result, "Existing URL must return existing_id"
    # All UUIDs unique
    assert len(set(result)) == 3, "All returned UUIDs must be unique"

    # Single commit (not N commits)
    assert (
        fake_session.commit_count == 1
    ), f"Expected single commit for bulk insert, got {fake_session.commit_count}"

    # URLs deduped: existing URL not re-inserted
    from core.db import ArticleCore

    inserted_urls = [
        obj.source_url for obj in fake_session.added_objects if isinstance(obj, ArticleCore)
    ]
    assert existing_url not in inserted_urls, "Existing URL must be deduped (not re-inserted)"
    assert "https://example.com/new1" in inserted_urls
    assert "https://example.com/new2" in inserted_urls

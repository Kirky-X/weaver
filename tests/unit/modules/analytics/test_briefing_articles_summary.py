# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""fetch_articles_for_briefing 返回 dict 必须携带 summary 键（R-briefing-001）。

briefing LLM payload 改为 summary 优先（token 优化），查询层必须把
ArticleCore.summary 取出并透传。本测试用 mock session 验证映射逻辑，
不依赖真实数据库（模型含 pgvector/ARRAY，sqlite 不可用）。
"""

import uuid
from collections import namedtuple
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.analytics.storage import AnalyticsStorage


def _make_storage_with_rows(rows: list) -> AnalyticsStorage:
    pool = MagicMock()
    session = MagicMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.session_context = MagicMock(return_value=ctx)
    return AnalyticsStorage(pool)


def _make_row(article_id: uuid.UUID, summary: str | None) -> namedtuple:
    article = SimpleNamespace(
        id=article_id,
        title="测试文章",
        category="经济",
        score=0.8,
        sentiment_score=0.1,
        credibility_score=0.9,
        publish_time=datetime(2026, 9, 12, 10, 0, 0),
    )
    Row = namedtuple("Row", ["ArticleCore", "body", "summary"])
    return Row(ArticleCore=article, body="正文内容", summary=summary)


class TestFetchArticlesForBriefingSummary:
    @pytest.mark.asyncio
    async def test_returned_dicts_contain_summary_key(self):
        article_id = uuid.uuid4()
        storage = _make_storage_with_rows([_make_row(article_id, "150字摘要内容")])

        result = await storage.fetch_articles_for_briefing(date(2026, 9, 12), "finance")

        assert len(result) == 1
        assert result[0]["summary"] == "150字摘要内容"
        assert result[0]["article_id"] == str(article_id)
        assert result[0]["body"] == "正文内容"

    @pytest.mark.asyncio
    async def test_null_summary_passes_through_as_none(self):
        storage = _make_storage_with_rows([_make_row(uuid.uuid4(), None)])

        result = await storage.fetch_articles_for_briefing(date(2026, 9, 12), "general")

        assert result[0]["summary"] is None

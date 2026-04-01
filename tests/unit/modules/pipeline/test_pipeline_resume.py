# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for pipeline resume and retry mechanism."""

from unittest.mock import AsyncMock

import pytest


def test_persist_status_has_processing():
    """验证 PersistStatus 包含 PROCESSING 状态"""
    from core.db.models import PersistStatus

    assert hasattr(PersistStatus, "PROCESSING"), "PersistStatus should have PROCESSING attribute"
    assert (
        PersistStatus.PROCESSING.value == "processing"
    ), "PROCESSING value should be 'processing' (lowercase to match DB enum)"


def test_article_has_processing_fields():
    """验证 Article 模型包含进度跟踪字段"""
    from core.db.models import Article

    # Check if the model has the expected columns by inspecting __table__
    column_names = [col.name for col in Article.__table__.columns]

    assert "processing_stage" in column_names, "Article should have processing_stage column"
    assert "processing_error" in column_names, "Article should have processing_error column"
    assert "retry_count" in column_names, "Article should have retry_count column"


@pytest.mark.asyncio
async def test_article_repo_has_get_stuck_articles_method():
    """验证 ArticleRepo 有 get_stuck_articles 方法"""
    from unittest.mock import MagicMock

    from modules.storage.postgres.article_repo import ArticleRepo

    mock_pool = MagicMock()
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_pool.session = MagicMock(return_value=mock_session)

    repo = ArticleRepo(mock_pool)
    assert hasattr(repo, "get_stuck_articles"), "ArticleRepo should have get_stuck_articles method"
    assert callable(repo.get_stuck_articles), "get_stuck_articles should be callable"


@pytest.mark.asyncio
async def test_article_repo_has_get_failed_articles_method():
    """验证 ArticleRepo 有 get_failed_articles 方法"""
    from unittest.mock import MagicMock

    from modules.storage.postgres.article_repo import ArticleRepo

    mock_pool = MagicMock()
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_pool.session = MagicMock(return_value=mock_session)

    repo = ArticleRepo(mock_pool)
    assert hasattr(
        repo, "get_failed_articles"
    ), "ArticleRepo should have get_failed_articles method"
    assert callable(repo.get_failed_articles), "get_failed_articles should be callable"


def test_pipeline_has_stage_tracking():
    """验证 Pipeline 有进度阶段跟踪常量"""
    from modules.pipeline.graph import PHASE1_STAGES, PHASE3_STAGES

    assert "classifier" in PHASE1_STAGES, "PHASE1_STAGES should contain classifier"
    assert "cleaner" in PHASE1_STAGES, "PHASE1_STAGES should contain cleaner"
    assert "categorizer" in PHASE1_STAGES, "PHASE1_STAGES should contain categorizer"
    assert "vectorize" in PHASE1_STAGES, "PHASE1_STAGES should contain vectorize"

    assert "re_vectorize" in PHASE3_STAGES, "PHASE3_STAGES should contain re_vectorize"
    assert "analyze" in PHASE3_STAGES, "PHASE3_STAGES should contain analyze"
    assert "credibility" in PHASE3_STAGES, "PHASE3_STAGES should contain credibility"
    assert "entity_extractor" in PHASE3_STAGES, "PHASE3_STAGES should contain entity_extractor"


def test_scheduler_jobs_has_retry_method():
    """验证 SchedulerJobs 有 retry_pipeline_processing 方法"""
    from modules.scheduler.jobs import SchedulerJobs

    assert hasattr(
        SchedulerJobs, "retry_pipeline_processing"
    ), "SchedulerJobs should have retry_pipeline_processing method"

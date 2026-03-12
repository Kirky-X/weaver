"""Tests for pipeline resume and retry mechanism."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta


def test_persist_status_has_processing():
    """验证 PersistStatus 包含 PROCESSING 状态"""
    from core.db.models import PersistStatus

    assert hasattr(PersistStatus, 'PROCESSING'), "PersistStatus should have PROCESSING attribute"
    assert PersistStatus.PROCESSING.value == "PROCESSING", "PROCESSING value should be 'PROCESSING'"


def test_article_has_processing_fields():
    """验证 Article 模型包含进度跟踪字段"""
    from core.db.models import Article

    # Check if the model has the expected columns by inspecting __table__
    column_names = [col.name for col in Article.__table__.columns]

    assert 'processing_stage' in column_names, "Article should have processing_stage column"
    assert 'processing_error' in column_names, "Article should have processing_error column"
    assert 'retry_count' in column_names, "Article should have retry_count column"


@pytest.mark.asyncio
async def test_get_stuck_articles():
    """验证 ArticleRepo 有 get_stuck_articles 方法"""
    from modules.storage.article_repo import ArticleRepo
    from unittest.mock import MagicMock

    # Create mock pool
    mock_pool = MagicMock()
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_pool.session = MagicMock(return_value=mock_session)

    # Create repo and check method exists
    repo = ArticleRepo(mock_pool)
    assert hasattr(repo, 'get_stuck_articles'), "ArticleRepo should have get_stuck_articles method"
    assert callable(getattr(repo, 'get_stuck_articles')), "get_stuck_articles should be callable"


@pytest.mark.asyncio
async def test_get_failed_articles():
    """验证 ArticleRepo 有 get_failed_articles 方法"""
    from modules.storage.article_repo import ArticleRepo
    from unittest.mock import MagicMock

    # Create mock pool
    mock_pool = MagicMock()
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_pool.session = MagicMock(return_value=mock_session)

    # Create repo and check method exists
    repo = ArticleRepo(mock_pool)
    assert hasattr(repo, 'get_failed_articles'), "ArticleRepo should have get_failed_articles method"
    assert callable(getattr(repo, 'get_failed_articles')), "get_failed_articles should be callable"


def test_pipeline_has_stage_tracking():
    """验证 Pipeline 有进度阶段跟踪常量"""
    from modules.pipeline.graph import PHASE1_STAGES, PHASE3_STAGES

    assert 'classifier' in PHASE1_STAGES, "PHASE1_STAGES should contain classifier"
    assert 'cleaner' in PHASE1_STAGES, "PHASE1_STAGES should contain cleaner"
    assert 'categorizer' in PHASE1_STAGES, "PHASE1_STAGES should contain categorizer"
    assert 'vectorize' in PHASE1_STAGES, "PHASE1_STAGES should contain vectorize"

    assert 're_vectorize' in PHASE3_STAGES, "PHASE3_STAGES should contain re_vectorize"
    assert 'analyze' in PHASE3_STAGES, "PHASE3_STAGES should contain analyze"
    assert 'credibility' in PHASE3_STAGES, "PHASE3_STAGES should contain credibility"
    assert 'entity_extractor' in PHASE3_STAGES, "PHASE3_STAGES should contain entity_extractor"

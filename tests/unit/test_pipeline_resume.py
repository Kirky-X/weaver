"""Tests for pipeline resume and retry mechanism."""

import pytest
from unittest.mock import AsyncMock, MagicMock


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

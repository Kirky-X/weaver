"""Tests for pipeline resume and retry mechanism."""

import pytest
from unittest.mock import AsyncMock, MagicMock


def test_persist_status_has_processing():
    """验证 PersistStatus 包含 PROCESSING 状态"""
    from core.db.models import PersistStatus

    assert hasattr(PersistStatus, 'PROCESSING'), "PersistStatus should have PROCESSING attribute"
    assert PersistStatus.PROCESSING.value == "PROCESSING", "PROCESSING value should be 'PROCESSING'"

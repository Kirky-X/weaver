# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Shared fixtures for LLM compare analytics tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event.bus import LLMCompareEvent
from modules.analytics.llm_compare.repo import EvalCompareRepo


@pytest.fixture
def mock_relational_pool():
    """Create mock relational pool for repo tests."""
    pool = MagicMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    pool.session = MagicMock(return_value=session)
    return pool


@pytest.fixture
def repo(mock_relational_pool):
    """Create EvalCompareRepo with mock pool."""
    return EvalCompareRepo(pool=mock_relational_pool)


@pytest.fixture
def sample_event():
    """Create sample LLMCompareEvent."""
    return LLMCompareEvent(
        timestamp=datetime(2026, 4, 14, 10, 30, 0, tzinfo=UTC),
        call_point="classifier",
        primary_model="gpt-4",
        candidate_model="claude-3",
        primary_latency=150.5,
        candidate_latency=200.3,
        primary_success=True,
        candidate_success=False,
    )


@pytest.fixture
def default_time_range():
    """Create default time range for queries."""
    return (
        datetime(2026, 4, 14, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC),
    )

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared fixtures for LLM compare analytics tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.event import LLMCompareEvent
from modules.analytics.llm_compare.repo import EvalCompareRepo
from tests.helpers import create_mock_relational_pool


@pytest.fixture
def mock_relational_pool():
    """Create mock relational pool for repo tests."""
    return create_mock_relational_pool()


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

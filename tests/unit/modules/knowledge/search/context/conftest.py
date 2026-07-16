# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared fixtures for Ladybug context tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_pool():
    """Create a mock graph pool for context builder tests."""
    pool = AsyncMock()
    pool.execute_query = AsyncMock(return_value=[])
    return pool

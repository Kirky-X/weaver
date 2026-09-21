# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Tests for analytics endpoint DI fix.

Verifies that _get_analytics_storage uses container.access.get_container()
instead of calling a FastAPI Depends function directly.

Moved from tests/integration/ — these tests mock the container, and the
integration suite hard-fails any test file containing mocks at collection
time (tests/integration/conftest.py). They belong in the unit suite.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch


class TestAnalyticsStorageFactory:
    """_get_analytics_storage must use container, not Depends."""

    def test_uses_container_not_depends(self):
        """Verify the function imports get_container from container.access."""
        from api.endpoints.analytics import _get_analytics_storage

        source = inspect.getsource(_get_analytics_storage)
        assert "container.access" in source or "get_container" in source
        assert "get_relational_pool" not in source

    def test_returns_analytics_storage(self):
        """Verify _get_analytics_storage wires the container pool into AnalyticsStorage."""
        from api.endpoints.analytics import _get_analytics_storage
        from modules.analytics import AnalyticsStorage

        mock_pool = MagicMock()
        mock_container = MagicMock()
        mock_container.relational_pool.return_value = mock_pool

        # Patch at the source module: the function lazy-imports
        # `from container.access import get_container` at call time, so
        # patching api.endpoints.analytics.get_container would NOT intercept it.
        with patch("container.access.get_container", return_value=mock_container):
            storage = _get_analytics_storage()

        assert isinstance(storage, AnalyticsStorage)
        assert storage._pool is mock_pool
        mock_container.relational_pool.assert_called_once_with()

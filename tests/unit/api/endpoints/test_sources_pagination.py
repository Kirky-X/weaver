# SPDX-License-Identifier: Apache-2.0

# SPDX-FileCopyrightText: © 2026 Kirky.X

"""GET /sources pagination tests.



验证：

- 分页参数越界返回 422

- 响应结构含 items/total/page/page_size/total_pages

- 分页逻辑正确（offset 计算、count 分离）

"""

from __future__ import annotations


from unittest.mock import AsyncMock, MagicMock


import pytest

from fastapi import FastAPI

from fastapi.testclient import TestClient


from api.middleware.api_response import register_exception_handlers


class TestSourcesPagination:
    """GET /sources 分页行为测试。"""

    @pytest.mark.asyncio
    async def test_default_pagination_returns_paginated_response(self) -> None:
        """默认参数返回分页结构。"""

        from api.endpoints.content.sources import list_sources

        from modules.ingestion.domain.models import SourceConfig

        mock_repo = MagicMock()

        mock_repo.list_sources = AsyncMock(
            return_value=[
                SourceConfig(id="s1", name="S1", url="https://s1.com/feed.xml"),
            ]
        )

        mock_repo.count_sources = AsyncMock(return_value=1)

        result = await list_sources(
            enabled_only=True,
            page=1,
            page_size=50,
            _="test-key",
            repo=mock_repo,
        )

        assert result.data.total == 1

        assert result.data.page == 1

        assert result.data.page_size == 50

        assert len(result.data.items) == 1

        assert result.data.total_pages == 1

    @pytest.mark.asyncio
    async def test_page_two_returns_correct_offset(self) -> None:
        """page=2 时 offset 正确传递。"""

        from api.endpoints.content.sources import list_sources

        mock_repo = MagicMock()

        mock_repo.list_sources = AsyncMock(return_value=[])

        mock_repo.count_sources = AsyncMock(return_value=100)

        await list_sources(
            enabled_only=True,
            page=3,
            page_size=10,
            _="test-key",
            repo=mock_repo,
        )

        mock_repo.list_sources.assert_called_once_with(
            enabled_only=True,
            limit=10,
            offset=20,
        )

        mock_repo.count_sources.assert_called_once_with(enabled_only=True)

    @pytest.mark.asyncio
    async def test_total_pages_calculation(self) -> None:
        """total_pages 向上取整。"""

        from api.endpoints.content.sources import list_sources

        mock_repo = MagicMock()

        mock_repo.list_sources = AsyncMock(return_value=[])

        mock_repo.count_sources = AsyncMock(return_value=51)

        result = await list_sources(
            enabled_only=True,
            page=1,
            page_size=50,
            _="test-key",
            repo=mock_repo,
        )

        assert result.data.total == 51

        assert result.data.total_pages == 2

    def test_page_size_over_200_returns_422(self) -> None:
        """page_size > 200 返回 422。"""

        from api.endpoints.content.sources import router

        from api.dependencies import get_source_config_repo

        from api.middleware.auth import verify_api_key

        app = FastAPI()

        register_exception_handlers(app)

        app.include_router(router)

        app.dependency_overrides[verify_api_key] = lambda: "test-key"

        app.dependency_overrides[get_source_config_repo] = lambda: MagicMock()

        client = TestClient(app)

        response = client.get("/sources?page_size=201")

        assert response.status_code == 422

    def test_page_zero_returns_422(self) -> None:
        """page < 1 返回 422。"""

        from api.endpoints.content.sources import router

        from api.dependencies import get_source_config_repo

        from api.middleware.auth import verify_api_key

        app = FastAPI()

        register_exception_handlers(app)

        app.include_router(router)

        app.dependency_overrides[verify_api_key] = lambda: "test-key"

        app.dependency_overrides[get_source_config_repo] = lambda: MagicMock()

        client = TestClient(app)

        response = client.get("/sources?page=0")

        assert response.status_code == 422

    def test_response_structure_has_required_fields(self) -> None:
        """HTTP 层响应体含 items/total/page/page_size/total_pages。"""

        from api.endpoints.content.sources import router

        app = FastAPI()

        register_exception_handlers(app)

        app.include_router(router)

        mock_repo = MagicMock()

        mock_repo.list_sources = AsyncMock(return_value=[])

        mock_repo.count_sources = AsyncMock(return_value=0)

        from api.dependencies import get_source_config_repo

        app.dependency_overrides[get_source_config_repo] = lambda: mock_repo

        # Also bypass auth

        from api.middleware.auth import verify_api_key

        app.dependency_overrides[verify_api_key] = lambda: "test-key"

        client = TestClient(app)

        response = client.get("/sources")

        assert response.status_code == 200

        body = response.json()

        data = body["data"]

        assert "items" in data

        assert "total" in data

        assert "page" in data

        assert "page_size" in data

        assert "total_pages" in data

        assert data["total"] == 0

        assert data["items"] == []

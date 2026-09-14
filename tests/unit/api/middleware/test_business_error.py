# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T024 业务错误码落地测试。

验证：
- BusinessError 异常携带 status_code/code/message
- 全局 handler 优先识别 BusinessError 并透传业务码
- 六处接线端点（article 404 / source 404 / pipeline 409 / 401 / 403）
  错误响应携带预期业务码
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware.api_response import register_exception_handlers
from api.schemas.response import ResponseCode
from core.exceptions import BusinessError


def _run_handler(app: FastAPI, exc_class: type, exc: Exception) -> tuple[int, dict]:
    """Invoke a registered exception handler and return (status_code, body)."""
    handler = app.exception_handlers[exc_class]
    response = asyncio.run(handler(MagicMock(), exc))
    return response.status_code, json.loads(response.body.decode())


class TestBusinessError:
    """BusinessError 异常本体契约。"""

    def test_is_exception_subclass(self) -> None:
        assert issubclass(BusinessError, Exception)

    def test_carries_status_code_code_message(self) -> None:
        exc = BusinessError(
            status_code=404,
            code=ResponseCode.ERR_ARTICLE_NOT_FOUND,
            message="Article 'x' not found",
        )
        assert exc.status_code == 404
        assert exc.code == ResponseCode.ERR_ARTICLE_NOT_FOUND
        assert exc.message == "Article 'x' not found"
        assert str(exc) == "Article 'x' not found"


class TestBusinessErrorHandler:
    """全局 handler 优先识别 BusinessError 并透传业务码。"""

    def test_handler_registered(self) -> None:
        app = FastAPI()
        register_exception_handlers(app)
        assert BusinessError in app.exception_handlers

    def test_business_error_code_passthrough(self) -> None:
        app = FastAPI()
        register_exception_handlers(app)

        exc = BusinessError(
            status_code=404,
            code=ResponseCode.ERR_ARTICLE_NOT_FOUND,
            message="Article 'abc' not found",
        )
        status, body = _run_handler(app, BusinessError, exc)

        assert status == 404
        assert body["code"] == ResponseCode.ERR_ARTICLE_NOT_FOUND
        assert body["message"] == "Article 'abc' not found"
        assert body["data"] is None
        assert "timestamp" in body

    def test_http_exception_default_mapping_unchanged(self) -> None:
        """未接线路径维持 HTTP 状态码到默认码的映射（行为不变）。"""
        from fastapi import HTTPException

        app = FastAPI()
        register_exception_handlers(app)

        exc = HTTPException(status_code=404, detail="Generic missing")
        status, body = _run_handler(app, HTTPException, exc)

        assert status == 404
        assert body["code"] == ResponseCode.ERR_NOT_FOUND
        assert body["message"] == "Generic missing"

    def test_response_body_built_from_error_response_model(self) -> None:
        """响应体由 ErrorResponse 模型构造（字段与模型定义一致）。"""
        from api.schemas.response import ErrorResponse

        app = FastAPI()
        register_exception_handlers(app)

        exc = BusinessError(
            status_code=409, code=ResponseCode.ERR_SOURCE_CONFLICT, message="locked"
        )
        _, body = _run_handler(app, BusinessError, exc)

        model_fields = set(ErrorResponse.model_fields)
        assert set(body) <= model_fields | {"data", "timestamp"}

    def test_testclient_end_to_end(self) -> None:
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/boom")
        def boom() -> None:
            raise BusinessError(
                status_code=401,
                code=ResponseCode.ERR_AUTH_FAILED,
                message="Missing API key",
            )

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/boom")

        assert response.status_code == 401
        assert response.json()["code"] == ResponseCode.ERR_AUTH_FAILED


class TestWiredEndpoints:
    """六处接线端点携带预期业务码。"""

    @pytest.mark.asyncio
    async def test_get_article_404_uses_article_code(self) -> None:
        from api.endpoints.content.articles import get_article

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)
        pool = MagicMock()
        pool.session.return_value.__aenter__ = AsyncMock(return_value=session)
        pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(BusinessError) as exc_info:
            await get_article(
                request=MagicMock(),
                article_id="12345678-1234-5678-1234-567812345678",
                api_key_id="test-key",
                pool=pool,
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == ResponseCode.ERR_ARTICLE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_source_404_uses_source_code(self) -> None:
        from api.endpoints.content.sources import get_source

        repo = AsyncMock()
        repo.get = AsyncMock(return_value=None)

        with pytest.raises(BusinessError) as exc_info:
            await get_source(source_id="missing", _="test-key", repo=repo)
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == ResponseCode.ERR_SOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_update_source_404_uses_source_code(self) -> None:
        from api.endpoints.content.sources import SourceUpdateRequest, update_source

        repo = AsyncMock()
        repo.get = AsyncMock(return_value=None)

        with pytest.raises(BusinessError) as exc_info:
            await update_source(
                source_id="missing",
                request=SourceUpdateRequest(name="n"),
                _="test-key",
                repo=repo,
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == ResponseCode.ERR_SOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_delete_source_404_uses_source_code(self) -> None:
        from api.endpoints.content.sources import delete_source

        repo = AsyncMock()
        repo.delete = AsyncMock(return_value=False)

        with pytest.raises(BusinessError) as exc_info:
            await delete_source(source_id="missing", _="test-key", repo=repo)
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == ResponseCode.ERR_SOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_pipeline_trigger_409_uses_conflict_code(self) -> None:
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        mock_cache.set_nx = AsyncMock(return_value=False)

        mock_source = MagicMock()
        mock_source.id = "test-source"
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources.return_value = [mock_source]

        with pytest.raises(BusinessError) as exc_info:
            await trigger_pipeline(
                request=TriggerRequest(source_id="test-source"),
                _="test-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.code == ResponseCode.ERR_PIPELINE_TRIGGER_FAILED

    @pytest.mark.asyncio
    async def test_verify_api_key_missing_401_uses_auth_code(self) -> None:
        from api.middleware.auth import verify_api_key

        with pytest.raises(BusinessError) as exc_info:
            await verify_api_key(key=None)
        assert exc_info.value.status_code == 401
        assert exc_info.value.code == ResponseCode.ERR_AUTH_FAILED

    @pytest.mark.asyncio
    async def test_verify_api_key_invalid_403_uses_forbidden_code(self) -> None:
        from api.middleware.auth import verify_api_key

        with patch("container.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.api.get_api_key.return_value = "valid-api-key-12345678901234567890"
            mock_settings.api.admin_api_key = None
            mock_get_settings.return_value = mock_settings

            with patch("api.middleware.auth.secrets.compare_digest", return_value=False):
                with pytest.raises(BusinessError) as exc_info:
                    await verify_api_key(key="invalid-api-key-1234567890123456")

        assert exc_info.value.status_code == 403
        assert exc_info.value.code == ResponseCode.ERR_FORBIDDEN

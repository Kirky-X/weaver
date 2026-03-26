# Copyright (c) 2026 KirkyX. All Rights Reserved
"""全局 API 响应包装与异常处理。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.schemas.response import ResponseCode
from core.observability.logging import get_logger

log = get_logger("api")


def _build_error_response(code: int, message: str, details: Any = None) -> dict[str, Any]:
    """构建错误响应体。"""
    body = {
        "code": code,
        "message": message,
        "timestamp": datetime.now(UTC).isoformat(),
        "data": None,
    }
    if details is not None:
        body["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers to FastAPI app.

    Handles:
    - RequestValidationError: validation errors (422)
    - HTTPException: raised by endpoints (400/404/503 etc.)
    - StarletteHTTPException: includes 404 for route not found
    - Exception: uncaught fallback exception
    """

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """将验证错误映射为统一错误响应。"""
        # Extract error details for more informative message
        errors = exc.errors()
        error_messages = []
        for error in errors:
            loc = " -> ".join(str(part) for part in error.get("loc", []))
            msg = error.get("msg", "Validation error")
            error_messages.append(f"{loc}: {msg}")

        message = "Validation failed: " + "; ".join(error_messages[:3])
        if len(error_messages) > 3:
            message += f" (and {len(error_messages) - 3} more)"

        body = _build_error_response(
            code=ResponseCode.ERR_INVALID_PARAM,
            message=message,
            details={"errors": errors},
        )
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Handle Starlette HTTPException (including 404 route not found)."""
        body = _build_error_response(
            code=exc.status_code * 100 + 1,  # e.g. 40401, 40001
            message=str(exc.detail) if exc.detail else f"HTTP {exc.status_code}",
        )
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """将 HTTPException 映射为统一错误响应。"""
        body = _build_error_response(
            code=exc.status_code * 100 + 1,  # e.g. 40401, 40001
            message=str(exc.detail) if exc.detail else f"HTTP {exc.status_code}",
        )
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """未捕获异常兜底处理器。"""
        log.exception("Unhandled exception", exc_info=exc)
        body = _build_error_response(
            code=ResponseCode.ERR_INTERNAL,
            message="Internal server error",
        )
        return JSONResponse(status_code=500, content=body)

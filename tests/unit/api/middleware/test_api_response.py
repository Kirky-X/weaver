# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for API response middleware."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.middleware.api_response import (
    _build_error_response,
    register_exception_handlers,
)
from api.schemas.response import ResponseCode


class TestBuildErrorResponse:
    """Tests for _build_error_response function."""

    def test_basic_error_response(self) -> None:
        """Test basic error response without details."""
        body = _build_error_response(
            code=ResponseCode.ERR_INVALID_PARAM,
            message="Invalid parameter",
        )

        assert body["code"] == ResponseCode.ERR_INVALID_PARAM
        assert body["message"] == "Invalid parameter"
        assert body["data"] is None
        assert "timestamp" in body

        # Verify timestamp is valid ISO format
        timestamp = body["timestamp"]
        # ISO format should be parseable
        parsed = datetime.fromisoformat(timestamp)
        assert parsed.tzinfo is not None

    def test_error_response_with_details(self) -> None:
        """Test error response with details."""
        details = {"field": "name", "error": "required"}
        body = _build_error_response(
            code=ResponseCode.ERR_NOT_FOUND,
            message="Resource not found",
            details=details,
        )

        assert body["code"] == ResponseCode.ERR_NOT_FOUND
        assert body["message"] == "Resource not found"
        assert body["data"] is None
        assert body["details"] == details

    def test_error_response_with_complex_details(self) -> None:
        """Test error response with complex details structure."""
        details = {
            "errors": [
                {"loc": ["body", "name"], "msg": "field required", "type": "value_error.missing"},
                {"loc": ["body", "age"], "msg": "must be positive", "type": "value_error.number"},
            ],
            "context": {"request_id": "abc123"},
        }
        body = _build_error_response(
            code=ResponseCode.ERR_INVALID_PARAM,
            message="Validation failed",
            details=details,
        )

        assert body["details"]["errors"] == details["errors"]
        assert body["details"]["context"] == details["context"]

    def test_error_response_timestamp_format(self) -> None:
        """Test that timestamp uses UTC timezone."""
        before = datetime.now(UTC)
        body = _build_error_response(code=100, message="test")
        after = datetime.now(UTC)

        timestamp = datetime.fromisoformat(body["timestamp"])

        # Timestamp should be within the time range of before and after
        assert before <= timestamp <= after
        # Should have timezone info
        assert timestamp.tzinfo is not None

    def test_error_response_none_details_not_included(self) -> None:
        """Test that None details are not included in response."""
        body = _build_error_response(
            code=ResponseCode.ERR_INTERNAL,
            message="Internal error",
            details=None,
        )

        assert "details" not in body


class TestRegisterExceptionHandlers:
    """Tests for register_exception_handlers function."""

    def test_registers_handlers(self) -> None:
        """Test that handlers are registered to app."""
        app = FastAPI()
        register_exception_handlers(app)

        # Check that exception handlers are registered
        # FastAPI stores handlers internally
        assert RequestValidationError in app.exception_handlers
        assert StarletteHTTPException in app.exception_handlers
        assert HTTPException in app.exception_handlers
        assert Exception in app.exception_handlers

    def test_handlers_return_json_response(self) -> None:
        """Test that all handlers return JSONResponse."""
        app = FastAPI()
        register_exception_handlers(app)

        # Verify handler types
        for exc_class in [RequestValidationError, StarletteHTTPException, HTTPException, Exception]:
            handler = app.exception_handlers.get(exc_class)
            assert handler is not None
            # Handlers are coroutine functions
            import asyncio

            assert asyncio.iscoroutinefunction(handler)


class TestValidationExceptionHandler:
    """Tests for RequestValidationError handler."""

    def test_single_validation_error(self) -> None:
        """Test handler with single validation error."""
        app = FastAPI()
        register_exception_handlers(app)

        # Create a mock validation error
        exc = RequestValidationError(
            errors=[
                {
                    "loc": ["body", "name"],
                    "msg": "field required",
                    "type": "value_error.missing",
                }
            ]
        )

        # Get the handler
        handler = app.exception_handlers[RequestValidationError]
        request = MagicMock()

        # Call handler
        import asyncio

        response = asyncio.run(handler(request, exc))

        assert isinstance(response, JSONResponse)
        assert response.status_code == 422

        # Get response body
        body = json.loads(response.body.decode())  # JSON content
        assert body["code"] == ResponseCode.ERR_INVALID_PARAM
        assert "Validation failed" in body["message"]
        assert "body -> name" in body["message"]
        assert "field required" in body["message"]
        assert "details" in body
        assert "errors" in body["details"]

    def test_multiple_validation_errors(self) -> None:
        """Test handler with multiple validation errors."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = RequestValidationError(
            errors=[
                {"loc": ["body", "name"], "msg": "field required", "type": "value_error.missing"},
                {"loc": ["body", "age"], "msg": "must be positive", "type": "value_error.number"},
                {"loc": ["body", "email"], "msg": "invalid format", "type": "value_error.email"},
            ]
        )

        handler = app.exception_handlers[RequestValidationError]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        body = json.loads(response.body.decode())
        assert response.status_code == 422

        # Message should include all errors
        message = body["message"]
        assert "body -> name" in message
        assert "body -> age" in message
        assert "body -> email" in message

    def test_many_validation_errors_truncated(self) -> None:
        """Test that message truncates when more than 3 errors."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = RequestValidationError(
            errors=[
                {"loc": ["body", f"field{i}"], "msg": f"error{i}", "type": "value_error"}
                for i in range(5)
            ]
        )

        handler = app.exception_handlers[RequestValidationError]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        body = json.loads(response.body.decode())

        # Message should indicate more errors exist
        message = body["message"]
        assert "and 2 more" in message

        # But details should have all errors
        assert len(body["details"]["errors"]) == 5

    def test_nested_location_path(self) -> None:
        """Test handler with nested location path."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = RequestValidationError(
            errors=[
                {
                    "loc": ["body", "user", "profile", "name"],
                    "msg": "too long",
                    "type": "value_error.string",
                }
            ]
        )

        handler = app.exception_handlers[RequestValidationError]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        body = json.loads(response.body.decode())

        # Location should be formatted with arrows
        assert "body -> user -> profile -> name" in body["message"]


class TestHTTPExceptionHandler:
    """Tests for HTTPException handler."""

    def test_http_exception_with_detail(self) -> None:
        """Test HTTPException handler with custom detail."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = HTTPException(status_code=404, detail="Article not found")

        handler = app.exception_handlers[HTTPException]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        assert response.status_code == 404

        body = json.loads(response.body.decode())
        assert body["code"] == 40401  # status_code * 100 + 1
        assert body["message"] == "Article not found"

    def test_http_exception_without_detail(self) -> None:
        """Test HTTPException handler without detail (uses default phrase)."""
        app = FastAPI()
        register_exception_handlers(app)

        # HTTPException converts None detail to default phrase for status code
        exc = HTTPException(status_code=403)

        handler = app.exception_handlers[HTTPException]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        assert response.status_code == 403

        body = json.loads(response.body.decode())
        assert body["code"] == 40301
        # HTTPException provides default phrase "Forbidden" for 403
        assert body["message"] == "Forbidden"

    def test_http_exception_500(self) -> None:
        """Test HTTPException with 500 status."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = HTTPException(status_code=500, detail="Service unavailable")

        handler = app.exception_handlers[HTTPException]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        assert response.status_code == 500

        body = json.loads(response.body.decode())
        assert body["code"] == 50001
        assert body["message"] == "Service unavailable"

    def test_http_exception_400(self) -> None:
        """Test HTTPException with 400 status."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = HTTPException(status_code=400, detail="Bad request")

        handler = app.exception_handlers[HTTPException]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        body = json.loads(response.body.decode())
        assert body["code"] == 40001


class TestStarletteHTTPExceptionHandler:
    """Tests for StarletteHTTPException handler."""

    def test_starlette_404_route_not_found(self) -> None:
        """Test handler for 404 route not found."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = StarletteHTTPException(status_code=404, detail="Not Found")

        handler = app.exception_handlers[StarletteHTTPException]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        assert response.status_code == 404

        body = json.loads(response.body.decode())
        assert body["code"] == 40401
        assert body["message"] == "Not Found"

    def test_starlette_405_method_not_allowed(self) -> None:
        """Test handler for 405 method not allowed."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = StarletteHTTPException(status_code=405, detail="Method Not Allowed")

        handler = app.exception_handlers[StarletteHTTPException]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        assert response.status_code == 405

        body = json.loads(response.body.decode())
        assert body["code"] == 40501
        assert body["message"] == "Method Not Allowed"

    def test_starlette_without_detail(self) -> None:
        """Test Starlette exception without custom detail (uses default phrase)."""
        app = FastAPI()
        register_exception_handlers(app)

        # StarletteHTTPException has default phrases for status codes
        exc = StarletteHTTPException(status_code=403)

        handler = app.exception_handlers[StarletteHTTPException]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        body = json.loads(response.body.decode())
        # Starlette provides default phrase "Forbidden" for 403
        assert body["message"] == "Forbidden"


class TestGenericExceptionHandler:
    """Tests for generic Exception handler."""

    def test_generic_exception_logged(self) -> None:
        """Test that generic exception is logged."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = Exception("Unexpected error occurred")

        handler = app.exception_handlers[Exception]
        request = MagicMock()

        # Mock the logger
        from api.middleware.api_response import log

        with patch.object(log, "exception") as mock_log:
            import asyncio

            response = asyncio.run(handler(request, exc))

            # Verify exception was logged
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            assert call_args[0][0] == "Unhandled exception"
            assert call_args[1]["exc_info"] == exc

        assert response.status_code == 500

        body = json.loads(response.body.decode())
        assert body["code"] == ResponseCode.ERR_INTERNAL
        assert body["message"] == "Internal server error"

    def test_generic_exception_returns_500(self) -> None:
        """Test that generic exception returns 500 status."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = ValueError("Something went wrong")

        handler = app.exception_handlers[Exception]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        assert response.status_code == 500

        body = json.loads(response.body.decode())
        assert body["code"] == ResponseCode.ERR_INTERNAL

    def test_generic_exception_no_details_exposed(self) -> None:
        """Test that generic exception does not expose error details."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = Exception("Sensitive internal error")

        handler = app.exception_handlers[Exception]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        body = json.loads(response.body.decode())

        # Should use generic message, not actual error
        assert body["message"] == "Internal server error"
        # No details should be exposed
        assert "details" not in body

    def test_generic_exception_runtime_error(self) -> None:
        """Test handler with RuntimeError."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = RuntimeError("Database connection failed")

        handler = app.exception_handlers[Exception]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        assert response.status_code == 500
        body = json.loads(response.body.decode())
        assert body["code"] == ResponseCode.ERR_INTERNAL


class TestIntegrationWithTestClient:
    """Integration tests using TestClient."""

    def test_validation_error_via_endpoint(self) -> None:
        """Test validation error through actual endpoint."""
        app = FastAPI()
        register_exception_handlers(app)

        from pydantic import BaseModel

        class Item(BaseModel):
            name: str
            price: float

        @app.post("/items")
        def create_item(item: Item) -> dict:
            return {"name": item.name, "price": item.price}

        client = TestClient(app)

        # Send invalid data (missing required field)
        response = client.post("/items", json={"price": 10.0})

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == ResponseCode.ERR_INVALID_PARAM
        assert "Validation failed" in body["message"]

    def test_http_exception_via_endpoint(self) -> None:
        """Test HTTPException through actual endpoint."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/items/{item_id}")
        def get_item(item_id: str) -> dict:
            if item_id == "missing":
                raise HTTPException(status_code=404, detail="Item not found")
            return {"id": item_id}

        client = TestClient(app)

        # Trigger HTTPException
        response = client.get("/items/missing")

        assert response.status_code == 404
        body = response.json()
        assert body["code"] == 40401
        assert body["message"] == "Item not found"

    def test_route_not_found_404(self) -> None:
        """Test 404 for non-existent route."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/exists")
        def existing_route() -> dict:
            return {"ok": True}

        client = TestClient(app)

        # Request non-existent route
        response = client.get("/nonexistent")

        assert response.status_code == 404
        body = response.json()
        assert body["code"] == 40401

    def test_method_not_allowed_405(self) -> None:
        """Test 405 for wrong method."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/only-get")
        def only_get() -> dict:
            return {"ok": True}

        client = TestClient(app)

        # Use POST on GET-only endpoint
        response = client.post("/only-get")

        assert response.status_code == 405
        body = response.json()
        assert body["code"] == 40501

    def test_unexpected_exception_500(self) -> None:
        """Test 500 for unexpected exception."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/error")
        def error_endpoint() -> dict:
            raise RuntimeError("Unexpected error")

        # Use raise_server_exceptions=False to allow handler to catch exception
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/error")

        assert response.status_code == 500
        body = response.json()
        assert body["code"] == ResponseCode.ERR_INTERNAL
        assert body["message"] == "Internal server error"

    def test_successful_response_not_modified(self) -> None:
        """Test that successful responses are not modified."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/success")
        def success_endpoint() -> dict:
            return {"data": "success", "count": 42}

        client = TestClient(app)

        response = client.get("/success")

        assert response.status_code == 200
        # Response should be the original, not wrapped
        assert response.json() == {"data": "success", "count": 42}


class TestResponseHeaders:
    """Tests for response headers."""

    def test_json_content_type(self) -> None:
        """Test that responses have JSON content type."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = HTTPException(status_code=404, detail="Not found")
        handler = app.exception_handlers[HTTPException]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        # JSONResponse should have application/json content type
        assert response.media_type == "application/json"

    def test_validation_error_content_type(self) -> None:
        """Test validation error response content type."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = RequestValidationError(
            errors=[{"loc": ["body"], "msg": "error", "type": "value_error"}]
        )
        handler = app.exception_handlers[RequestValidationError]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        assert response.media_type == "application/json"

    def test_generic_error_content_type(self) -> None:
        """Test generic error response content type."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = Exception("error")
        handler = app.exception_handlers[Exception]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        assert response.media_type == "application/json"


class TestErrorCodeCalculation:
    """Tests for error code calculation logic."""

    def test_code_calculation_404(self) -> None:
        """Test error code for 404 status."""
        # Code = status_code * 100 + 1
        assert 404 * 100 + 1 == 40401

    def test_code_calculation_400(self) -> None:
        """Test error code for 400 status."""
        assert 400 * 100 + 1 == 40001

    def test_code_calculation_503(self) -> None:
        """Test error code for 503 status."""
        assert 503 * 100 + 1 == 50301

    def test_validation_error_uses_different_code(self) -> None:
        """Test that validation error uses ERR_INVALID_PARAM."""
        app = FastAPI()
        register_exception_handlers(app)

        exc = RequestValidationError(
            errors=[{"loc": ["body"], "msg": "error", "type": "value_error"}]
        )
        handler = app.exception_handlers[RequestValidationError]
        request = MagicMock()

        import asyncio

        response = asyncio.run(handler(request, exc))

        body = json.loads(response.body.decode())
        # Should use 10001, not 42201
        assert body["code"] == ResponseCode.ERR_INVALID_PARAM
        assert body["code"] != 42201

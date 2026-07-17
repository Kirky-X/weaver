# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for trend detection API endpoint (T016 / R-trend-004).

Covers:
- GET /trends/detection — trend detection over a window with optional entity_type
- Router registration (route exists, GET method)
- Parameter validation (window in {7d, 30d}, entity_type optional)
- Response serialization (TrendDetectionResult → APIResponse[dict])
- No-data contract (R-trend-003/004): HTTP 200 with status='insufficient_data',
  trends=[], list=[] — data insufficiency is NOT an error
- Error propagation (Rule 12: HTTP 500 on service failure, 400 on ValueError)
- entity_type forwarding to service
- All 5 TrendDetectionResult fields serialized

Patch surface: ``api.endpoints.trends._get_trend_detection_service`` returns a
mock TrendDetector. Tests do NOT hit the real service/DB.

Spec compliance (R-trend-004):
    status='insufficient_data' returns HTTP 200 (not 400/500). This is
    distinct from the no-data contract in R-sentiment-002 — insufficient
    EventNode count is a legitimate state reported via the status field,
    not an error condition.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from api.endpoints.trends import router
from modules.trend.models import TrendDetectionResult
from tests.helpers import create_test_client


def _make_detection_result(
    *,
    window_days: int = 7,
    entity_type: str | None = None,
    trends: list | None = None,
    list_field: list | None = None,
    status: str = "ok",
) -> TrendDetectionResult:
    """Build a TrendDetectionResult fixture for tests.

    ``list_field`` parameter name avoids shadowing the ``list`` builtin
    in the test helper signature (the dataclass field itself is ``list``
    per spec R-trend-001).
    """
    return TrendDetectionResult(
        window_days=window_days,
        entity_type=entity_type,
        trends=trends if trends is not None else [],
        list=list_field if list_field is not None else [],
        status=status,
    )


class TestTrendsDetectionRouterRegistration:
    """Tests for /detection route registration."""

    def test_detection_route_exists(self) -> None:
        """GET /trends/detection route is registered."""
        routes = [route.path for route in router.routes]
        assert "/trends/detection" in routes

    def test_detection_route_method_is_get(self) -> None:
        """Detection route accepts GET method."""
        from fastapi.routing import APIRoute

        detection_routes = [
            r for r in router.routes if getattr(r, "path", "") == "/trends/detection"
        ]
        assert len(detection_routes) == 1
        route = detection_routes[0]
        assert isinstance(route, APIRoute)
        assert "GET" in route.methods

    def test_sentiment_route_still_exists(self) -> None:
        """GET /trends/sentiment route (T013) still registered after T016."""
        routes = [route.path for route in router.routes]
        assert "/trends/sentiment" in routes
        assert "/trends/detection" in routes


class TestGetTrendDetection:
    """Tests for GET /trends/detection endpoint (R-trend-004)."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.client = create_test_client(router)

    def test_detection_ok_status_returns_trends(self) -> None:
        """GET with window=7d returns ok status with trends (R-trend-004)."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(
            return_value=_make_detection_result(
                window_days=7,
                status="ok",
                trends=[
                    {
                        "entity_name": "OpenAI",
                        "trend_score": 0.42,
                        "direction": "up",
                        "frequency_change": 0.5,
                        "current_count": 30,
                        "previous_count": 20,
                    }
                ],
                list_field=[
                    {"day": "2026-07-17", "mentions": 5, "count": 5},
                ],
            )
        )

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=7d")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["message"] == "success"
        assert body["data"]["status"] == "ok"
        assert body["data"]["window_days"] == 7
        assert len(body["data"]["trends"]) == 1
        assert body["data"]["trends"][0]["entity_name"] == "OpenAI"
        assert body["data"]["trends"][0]["trend_score"] == 0.42
        assert body["data"]["trends"][0]["direction"] == "up"
        assert len(body["data"]["list"]) == 1
        assert body["data"]["list"][0]["day"] == "2026-07-17"

    def test_detection_insufficient_data_returns_200(self) -> None:
        """status='insufficient_data' → HTTP 200 with empty trends (R-trend-003/004).

        Data insufficiency is NOT an error — the endpoint returns HTTP 200
        with status='insufficient_data', trends=[], list=[].
        """
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(
            return_value=_make_detection_result(
                window_days=7,
                status="insufficient_data",
                trends=[],
                list_field=[],
            )
        )

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=7d")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "insufficient_data"
        assert body["data"]["trends"] == []
        assert body["data"]["list"] == []

    def test_detection_default_window_7d(self) -> None:
        """GET without window defaults to 7d."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(return_value=_make_detection_result(window_days=7))

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection")

        assert response.status_code == 200
        mock_service.detect_trends.assert_called_once_with(
            window_days=7,
            entity_type=None,
        )

    def test_detection_window_30d(self) -> None:
        """GET with window=30d forwards window_days=30 to service."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(return_value=_make_detection_result(window_days=30))

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=30d")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["window_days"] == 30
        mock_service.detect_trends.assert_called_once_with(
            window_days=30,
            entity_type=None,
        )

    def test_detection_invalid_window_format_returns_400(self) -> None:
        """Invalid window format (not Nd) → HTTP 400."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(return_value=_make_detection_result())

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=invalid")

        assert response.status_code == 400
        body = response.json()
        assert "detail" in body
        mock_service.detect_trends.assert_not_called()

    def test_detection_unsupported_window_value_returns_400(self) -> None:
        """Unsupported window value (5d) → HTTP 400 (only 7d/30d allowed)."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(return_value=_make_detection_result())

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=5d")

        assert response.status_code == 400
        body = response.json()
        assert "detail" in body
        mock_service.detect_trends.assert_not_called()

    def test_detection_entity_type_optional(self) -> None:
        """entity_type is optional — None aggregates across all entities."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(
            return_value=_make_detection_result(
                entity_type=None,
                status="ok",
                trends=[
                    {"entity_name": "OpenAI", "trend_score": 0.3, "direction": "up"},
                    {"entity_name": "TechCorp", "trend_score": -0.3, "direction": "down"},
                ],
            )
        )

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=7d")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["entity_type"] is None
        assert len(body["data"]["trends"]) == 2
        mock_service.detect_trends.assert_called_once_with(
            window_days=7,
            entity_type=None,
        )

    def test_detection_entity_type_filter_forwarded(self) -> None:
        """entity_type param is forwarded to service.detect_trends."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(
            return_value=_make_detection_result(
                entity_type="OpenAI",
                status="ok",
                trends=[
                    {"entity_name": "OpenAI", "trend_score": 0.5, "direction": "up"},
                ],
            )
        )

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=7d&entity_type=OpenAI")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["entity_type"] == "OpenAI"
        mock_service.detect_trends.assert_called_once_with(
            window_days=7,
            entity_type="OpenAI",
        )

    def test_detection_entity_type_with_special_chars(self) -> None:
        """entity_type with URL-encoded special chars is decoded and forwarded."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(
            return_value=_make_detection_result(entity_type="Johnson & Johnson")
        )

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            # %26 = &, %20 = space — entity names may contain these.
            response = self.client.get(
                "/trends/detection?window=7d&entity_type=Johnson%20%26%20Johnson"
            )

        assert response.status_code == 200
        mock_service.detect_trends.assert_called_once_with(
            window_days=7,
            entity_type="Johnson & Johnson",
        )

    def test_detection_service_error_returns_500(self) -> None:
        """Service error returns HTTP 500 (Rule 12: fail loud)."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(side_effect=RuntimeError("Graph DB connection lost"))

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=7d")

        assert response.status_code == 500
        body = response.json()
        assert "detail" in body

    def test_detection_service_value_error_returns_400(self) -> None:
        """ValueError from service (validation) returns HTTP 400, not 500.

        Although the endpoint pre-validates window, the service may still
        raise ValueError for edge cases (defense-in-depth).
        """
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(
            side_effect=ValueError("window_days must be one of [7, 30]")
        )

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=7d")

        assert response.status_code == 400
        body = response.json()
        assert "detail" in body

    def test_detection_response_has_timestamp(self) -> None:
        """Response includes timestamp field (APIResponse schema)."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(return_value=_make_detection_result())

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=7d")

        body = response.json()
        assert "timestamp" in body

    def test_detection_serializes_all_5_fields(self) -> None:
        """All 5 TrendDetectionResult fields are serialized in response data."""
        mock_service = MagicMock()
        trends_data = [
            {
                "entity_name": "OpenAI",
                "trend_score": 0.42,
                "direction": "up",
                "frequency_change": 0.5,
                "current_count": 30,
                "previous_count": 20,
            }
        ]
        list_data = [{"day": "2026-07-17", "mentions": 5, "count": 5}]
        mock_service.detect_trends = AsyncMock(
            return_value=_make_detection_result(
                window_days=7,
                entity_type="OpenAI",
                trends=trends_data,
                list_field=list_data,
                status="ok",
            )
        )

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=7d&entity_type=OpenAI")

        body = response.json()
        data = body["data"]
        # All 5 fields present (spec R-trend-001).
        assert "window_days" in data
        assert "entity_type" in data
        assert "trends" in data
        assert "list" in data
        assert "status" in data
        # Field values match input.
        assert data["window_days"] == 7
        assert data["entity_type"] == "OpenAI"
        assert data["trends"] == trends_data
        assert data["list"] == list_data
        assert data["status"] == "ok"

    def test_detection_insufficient_data_with_entity_type(self) -> None:
        """insufficient_data + entity_type filter → HTTP 200 with echoed entity_type."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(
            return_value=_make_detection_result(
                window_days=7,
                entity_type="NonexistentEntity",
                status="insufficient_data",
                trends=[],
                list_field=[],
            )
        )

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=7d&entity_type=NonexistentEntity")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "insufficient_data"
        assert body["data"]["entity_type"] == "NonexistentEntity"
        assert body["data"]["trends"] == []
        assert body["data"]["list"] == []

    def test_detection_empty_trends_when_ok_status(self) -> None:
        """ok status with empty trends (all entities at boundary) is valid."""
        mock_service = MagicMock()
        mock_service.detect_trends = AsyncMock(
            return_value=_make_detection_result(
                window_days=7,
                status="ok",
                trends=[],
                list_field=[],
            )
        )

        with patch(
            "api.endpoints.trends._get_trend_detection_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/detection?window=7d")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "ok"
        assert body["data"]["trends"] == []

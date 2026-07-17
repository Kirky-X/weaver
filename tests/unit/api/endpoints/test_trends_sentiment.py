# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for sentiment trend API endpoint (T013 / R-sentiment-003).

Covers:
- GET /trends/sentiment — sentiment trend analysis for an entity over a window
- Router registration (prefix, tags, routes)
- Parameter validation (entity required, window in {7d, 30d})
- Response serialization (SentimentTrendResult → APIResponse[dict])
- No-data contract (R-sentiment-002): HTTP 200 with empty stable result
- Error propagation (Rule 12: HTTP 500 on service failure)

Patch surface: ``api.endpoints.trends._get_sentiment_trend_service`` returns a
mock SentimentTrendAnalyzer. Tests do NOT hit the real service/DB.

Spec conflict (Rule 7 — exposed):
    R-sentiment-003 says "entity 参数可选" (entity param optional), but
    Constraints say "entity_name 和 community_id 不能同时为 None". Since the
    endpoint only exposes ``entity`` (no community_id param), entity is
    declared Optional in the signature (spec compliance) but the handler
    returns HTTP 400 when entity is missing (Constraints compliance + user
    task spec: "entity 必传（HTTP 400 缺失时）").
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from api.endpoints.trends import router
from modules.trend.models import SentimentTrendResult
from tests.helpers import create_test_client


def _make_trend_result(
    *,
    entity_name: str | None = "TestEntity",
    window_days: int = 7,
    shifts: list | None = None,
    list_field: list | None = None,
    avg_shift: float = 0.0,
    trend_direction: str = "stable",
) -> SentimentTrendResult:
    """Build a SentimentTrendResult fixture for tests.

    ``list_field`` parameter name avoids shadowing the ``list`` builtin
    in the test helper signature (the dataclass field itself is ``list``
    per spec R-sentiment-001).
    """
    return SentimentTrendResult(
        entity_name=entity_name,
        window_days=window_days,
        shifts=shifts if shifts is not None else [],
        list=list_field if list_field is not None else [],
        avg_shift=avg_shift,
        trend_direction=trend_direction,
    )


class TestTrendsRouterRegistration:
    """Tests for trends router registration."""

    def test_router_prefix(self) -> None:
        """Router prefix is /trends."""
        assert router.prefix == "/trends"

    def test_router_tags(self) -> None:
        """Router has 'trends' tag."""
        assert "trends" in router.tags

    def test_sentiment_route_exists(self) -> None:
        """GET /trends/sentiment route is registered."""
        routes = [route.path for route in router.routes]
        assert "/trends/sentiment" in routes

    def test_sentiment_route_method_is_get(self) -> None:
        """Sentiment route accepts GET method."""
        from fastapi.routing import APIRoute

        sentiment_routes = [
            r for r in router.routes if getattr(r, "path", "") == "/trends/sentiment"
        ]
        assert len(sentiment_routes) == 1
        route = sentiment_routes[0]
        assert isinstance(route, APIRoute)
        assert "GET" in route.methods


class TestGetSentimentTrend:
    """Tests for GET /trends/sentiment endpoint (R-sentiment-003)."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.client = create_test_client(router)

    def test_get_sentiment_trend_up_direction(self) -> None:
        """GET with entity + window=7d returns up trend (avg_shift > 0.1)."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(
            return_value=_make_trend_result(
                entity_name="OpenAI",
                window_days=7,
                avg_shift=0.5,
                trend_direction="up",
                shifts=[
                    {
                        "article_id": "art-1",
                        "entity_name": "OpenAI",
                        "shift_value": 0.5,
                        "detected_at": "2026-07-17T10:00:00+00:00",
                    }
                ],
                list_field=[{"day": "2026-07-17", "avg_shift": 0.5, "count": 1}],
            )
        )

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=OpenAI&window=7d")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["message"] == "success"
        assert body["data"]["entity_name"] == "OpenAI"
        assert body["data"]["window_days"] == 7
        assert body["data"]["avg_shift"] == 0.5
        assert body["data"]["trend_direction"] == "up"
        assert len(body["data"]["shifts"]) == 1
        assert body["data"]["shifts"][0]["shift_value"] == 0.5
        assert len(body["data"]["list"]) == 1
        assert body["data"]["list"][0]["day"] == "2026-07-17"

    def test_get_sentiment_trend_down_direction(self) -> None:
        """GET returns down trend (avg_shift < -0.1)."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(
            return_value=_make_trend_result(
                entity_name="TechCorp",
                avg_shift=-0.3,
                trend_direction="down",
            )
        )

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=TechCorp&window=7d")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["trend_direction"] == "down"
        assert body["data"]["avg_shift"] == -0.3

    def test_get_sentiment_trend_stable_direction(self) -> None:
        """GET returns stable trend (|avg_shift| <= 0.1)."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(
            return_value=_make_trend_result(
                entity_name="StableEntity",
                avg_shift=0.05,
                trend_direction="stable",
            )
        )

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=StableEntity")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["trend_direction"] == "stable"

    def test_get_sentiment_trend_no_data_returns_empty_stable(self) -> None:
        """No shifts in window → HTTP 200 with empty stable result (R-sentiment-002)."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(
            return_value=_make_trend_result(
                entity_name="NoDataEntity",
                window_days=7,
                shifts=[],
                list_field=[],
                avg_shift=0.0,
                trend_direction="stable",
            )
        )

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=NoDataEntity&window=7d")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["shifts"] == []
        assert body["data"]["list"] == []
        assert body["data"]["avg_shift"] == 0.0
        assert body["data"]["trend_direction"] == "stable"

    def test_get_sentiment_trend_missing_entity_returns_400(self) -> None:
        """Missing entity param → HTTP 400 (Constraints: at least one filter required).

        Spec R-sentiment-003 says entity is optional, but Constraints say
        "entity_name 和 community_id 不能同时为 None". The endpoint only
        exposes entity (no community_id param), so missing entity means no
        filter → HTTP 400 (user task spec: "entity 必传（HTTP 400 缺失时）").
        """
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(return_value=_make_trend_result())

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?window=7d")

        assert response.status_code == 400
        body = response.json()
        assert "detail" in body
        # Service MUST NOT be called when entity is missing.
        mock_service.analyze_trend.assert_not_called()

    def test_get_sentiment_trend_empty_entity_returns_400(self) -> None:
        """Empty entity string → HTTP 400 (whitespace-only is not a valid entity)."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(return_value=_make_trend_result())

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=&window=7d")

        assert response.status_code == 400
        mock_service.analyze_trend.assert_not_called()

    def test_get_sentiment_trend_default_window_7d(self) -> None:
        """GET without window defaults to 7d."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(return_value=_make_trend_result(window_days=7))

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=TestEntity")

        assert response.status_code == 200
        # Service called with window_days=7 (default).
        mock_service.analyze_trend.assert_called_once_with(
            entity_name="TestEntity",
            window_days=7,
        )

    def test_get_sentiment_trend_window_30d(self) -> None:
        """GET with window=30d forwards window_days=30 to service."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(return_value=_make_trend_result(window_days=30))

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=TestEntity&window=30d")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["window_days"] == 30
        mock_service.analyze_trend.assert_called_once_with(
            entity_name="TestEntity",
            window_days=30,
        )

    def test_get_sentiment_trend_invalid_window_format_returns_400(self) -> None:
        """Invalid window format (not Nd) → HTTP 400."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(return_value=_make_trend_result())

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=TestEntity&window=invalid")

        assert response.status_code == 400
        body = response.json()
        assert "detail" in body
        mock_service.analyze_trend.assert_not_called()

    def test_get_sentiment_trend_unsupported_window_value_returns_400(self) -> None:
        """Unsupported window value (5d) → HTTP 400 (only 7d/30d allowed)."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(return_value=_make_trend_result())

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=TestEntity&window=5d")

        assert response.status_code == 400
        body = response.json()
        assert "detail" in body
        mock_service.analyze_trend.assert_not_called()

    def test_get_sentiment_trend_service_error_returns_500(self) -> None:
        """Service error returns HTTP 500 (Rule 12: fail loud)."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=TestEntity&window=7d")

        assert response.status_code == 500
        body = response.json()
        assert "detail" in body

    def test_get_sentiment_trend_response_has_timestamp(self) -> None:
        """Response includes timestamp field (APIResponse schema)."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(return_value=_make_trend_result())

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=TestEntity")

        body = response.json()
        assert "timestamp" in body

    def test_get_sentiment_trend_forwards_entity_to_service(self) -> None:
        """Endpoint forwards entity param as entity_name to service.analyze_trend."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(return_value=_make_trend_result())

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            self.client.get("/trends/sentiment?entity=SpecialEntity&window=7d")

        mock_service.analyze_trend.assert_called_once_with(
            entity_name="SpecialEntity",
            window_days=7,
        )

    def test_get_sentiment_trend_serializes_all_fields(self) -> None:
        """All 6 SentimentTrendResult fields are serialized in response data."""
        mock_service = MagicMock()
        shifts_data = [
            {
                "article_id": "art-1",
                "entity_name": "TestEntity",
                "shift_value": 0.2,
                "before_avg": 0.1,
                "after_avg": 0.3,
                "detected_at": "2026-07-17T10:00:00+00:00",
            }
        ]
        list_data = [{"day": "2026-07-17", "avg_shift": 0.2, "count": 1}]
        mock_service.analyze_trend = AsyncMock(
            return_value=_make_trend_result(
                entity_name="TestEntity",
                window_days=7,
                shifts=shifts_data,
                list_field=list_data,
                avg_shift=0.2,
                trend_direction="up",
            )
        )

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=TestEntity&window=7d")

        body = response.json()
        data = body["data"]
        # All 6 fields present (spec R-sentiment-001).
        assert "entity_name" in data
        assert "window_days" in data
        assert "shifts" in data
        assert "list" in data
        assert "avg_shift" in data
        assert "trend_direction" in data
        # Field values match input.
        assert data["entity_name"] == "TestEntity"
        assert data["window_days"] == 7
        assert data["shifts"] == shifts_data
        assert data["list"] == list_data
        assert data["avg_shift"] == 0.2
        assert data["trend_direction"] == "up"

    def test_get_sentiment_trend_entity_with_special_chars(self) -> None:
        """Entity with URL-encoded special chars is decoded and forwarded."""
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(return_value=_make_trend_result())

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            # %26 = &, %20 = space — entity names may contain these.
            response = self.client.get("/trends/sentiment?entity=Johnson%20%26%20Johnson&window=7d")

        assert response.status_code == 200
        mock_service.analyze_trend.assert_called_once_with(
            entity_name="Johnson & Johnson",
            window_days=7,
        )

    def test_get_sentiment_trend_service_value_error_returns_400(self) -> None:
        """ValueError from service (validation) returns HTTP 400, not 500.

        Although the endpoint pre-validates entity + window, the service may
        still raise ValueError for edge cases (e.g. both entity_name and
        community_id None, which the endpoint prevents, but defense-in-depth).
        ValueError indicates client input problem → 400.
        """
        mock_service = MagicMock()
        mock_service.analyze_trend = AsyncMock(
            side_effect=ValueError("window_days must be one of [7, 30]")
        )

        with patch(
            "api.endpoints.trends._get_sentiment_trend_service",
            return_value=mock_service,
        ):
            response = self.client.get("/trends/sentiment?entity=TestEntity&window=7d")

        assert response.status_code == 400
        body = response.json()
        assert "detail" in body

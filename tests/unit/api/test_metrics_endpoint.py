# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Test /metrics endpoint has only one handler.

Validates GAP-M04 fix: duplicate /metrics route registration removed,
keeping only the version with optional authentication.
"""

from main import create_app


class TestMetricsEndpoint:
    """Verify /metrics has exactly one route handler."""

    def test_metrics_route_has_single_handler(self) -> None:
        """/metrics route should have exactly one handler."""
        app = create_app()

        # Count routes matching /metrics
        metrics_routes = [
            route for route in app.routes if getattr(route, "path", None) == "/metrics"
        ]
        assert (
            len(metrics_routes) == 1
        ), f"Expected exactly 1 /metrics route, found {len(metrics_routes)}"

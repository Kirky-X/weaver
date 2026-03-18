# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Shared API client wrapper for E2E tests."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


class E2EClient:
    """Thin wrapper around FastAPI TestClient with Weaver-specific helpers.

    Provides convenience methods for common E2E operations and automatically
    includes authentication headers.
    """

    def __init__(self, client: TestClient, api_key: str) -> None:
        """Initialize the E2E client.

        Args:
            client: FastAPI TestClient instance.
            api_key: API key for authentication.
        """
        self._client = client
        self._api_key = api_key

    @property
    def headers(self) -> dict[str, str]:
        """Standard authenticated headers."""
        return {"X-API-Key": self._api_key}

    # ── Health ─────────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        """Check /health endpoint (no auth required).

        Returns:
            Health check response data.
        """
        response = self._client.get("/health")
        response.raise_for_status()
        return response.json()

    # ── Sources ────────────────────────────────────────────────────

    def create_source(
        self,
        source_id: str,
        name: str,
        url: str,
        source_type: str = "rss",
        enabled: bool = True,
        interval_minutes: int = 30,
    ) -> dict[str, Any]:
        """Create a source via POST /api/v1/sources.

        Args:
            source_id: Unique source identifier.
            name: Human-readable name.
            url: Feed URL (RSS/Atom).
            source_type: Type of source.
            enabled: Whether the source is active.
            interval_minutes: Crawl interval in minutes.

        Returns:
            Created source data.
        """
        response = self._client.post(
            "/api/v1/sources",
            json={
                "id": source_id,
                "name": name,
                "url": url,
                "source_type": source_type,
                "enabled": enabled,
                "interval_minutes": interval_minutes,
            },
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()

    def list_sources(
        self,
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        """List sources via GET /api/v1/sources.

        Args:
            enabled_only: Only return enabled sources.

        Returns:
            List of source configs.
        """
        response = self._client.get(
            "/api/v1/sources",
            params={"enabled_only": enabled_only},
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        """Get a specific source by ID.

        Args:
            source_id: Source identifier.

        Returns:
            Source data or None if not found.
        """
        response = self._client.get(
            f"/api/v1/sources/{source_id}",
            headers=self.headers,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def update_source(
        self,
        source_id: str,
        **updates: Any,
    ) -> dict[str, Any]:
        """Update a source via PUT /api/v1/sources/{source_id}.

        Args:
            source_id: Source identifier.
            **updates: Fields to update.

        Returns:
            Updated source data.
        """
        response = self._client.put(
            f"/api/v1/sources/{source_id}",
            json=updates,
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()

    def delete_source(self, source_id: str) -> None:
        """Delete a source via DELETE /api/v1/sources/{source_id}.

        Args:
            source_id: Source identifier.
        """
        response = self._client.delete(
            f"/api/v1/sources/{source_id}",
            headers=self.headers,
        )
        response.raise_for_status()

    # ── Pipeline ──────────────────────────────────────────────────

    def trigger_pipeline(
        self,
        source_id: str | None = None,
        force: bool = False,
        max_items: int | None = None,
    ) -> dict[str, Any]:
        """Trigger pipeline via POST /api/v1/pipeline/trigger.

        Args:
            source_id: Specific source to crawl, or None for all.
            force: Force re-crawl even if recently crawled.
            max_items: Maximum items per source.

        Returns:
            Task information with task_id.
        """
        payload: dict[str, Any] = {"force": force}
        if source_id is not None:
            payload["source_id"] = source_id
        if max_items is not None:
            payload["max_items"] = max_items

        response = self._client.post(
            "/api/v1/pipeline/trigger",
            json=payload,
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """Get task status via GET /api/v1/pipeline/tasks/{task_id}.

        Args:
            task_id: Task identifier.

        Returns:
            Task status data or None if not found.
        """
        response = self._client.get(
            f"/api/v1/pipeline/tasks/{task_id}",
            headers=self.headers,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def get_queue_stats(self) -> dict[str, Any]:
        """Get queue stats via GET /api/v1/pipeline/queue/stats.

        Returns:
            Queue statistics.
        """
        response = self._client.get(
            "/api/v1/pipeline/queue/stats",
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()

    # ── Articles ───────────────────────────────────────────────────

    def list_articles(
        self,
        page: int = 1,
        page_size: int = 20,
        category: str | None = None,
        source_host: str | None = None,
        min_score: float | None = None,
        sort_by: str = "publish_time",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """List articles via GET /api/v1/articles.

        Args:
            page: Page number (1-indexed).
            page_size: Items per page.
            category: Filter by category.
            source_host: Filter by source host.
            min_score: Minimum quality score.
            sort_by: Sort field.
            sort_order: Sort direction (asc/desc).

        Returns:
            Paginated article list.
        """
        params: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if category is not None:
            params["category"] = category
        if source_host is not None:
            params["source_host"] = source_host
        if min_score is not None:
            params["min_score"] = min_score

        response = self._client.get(
            "/api/v1/articles",
            params=params,
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()

    def get_article(self, article_id: str) -> dict[str, Any] | None:
        """Get a specific article by ID.

        Args:
            article_id: Article UUID.

        Returns:
            Article data or None if not found.
        """
        response = self._client.get(
            f"/api/v1/articles/{article_id}",
            headers=self.headers,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    # ── Graph ─────────────────────────────────────────────────────

    def get_entity(self, entity_name: str) -> dict[str, Any] | None:
        """Get entity and its relations via GET /api/v1/graph/entities/{name}.

        Args:
            entity_name: Name of the entity to query.

        Returns:
            Entity data or None if not found.
        """
        response = self._client.get(
            f"/api/v1/graph/entities/{entity_name}",
            headers=self.headers,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

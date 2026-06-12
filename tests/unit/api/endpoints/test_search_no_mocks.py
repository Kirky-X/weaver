# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for search endpoint mock detection and dependency injection (Tasks 2.1-2.3).

These tests verify that the causal/temporal search endpoints use proper
dependency injection instead of inline mock services, and that the
Endpoints registry provides the required service getters.
"""

from pathlib import Path

import pytest

# ── Task 2.1: Mock detection in search.py ──────────────────────────────


class TestSearchEndpointNoMocks:
    """Verify that search.py does NOT contain inline mock service classes.

    The causal and temporal search endpoints should obtain EmbeddingService
    and IntentClassifier through the Endpoints dependency registry, not by
    defining mock classes inline.
    """

    SEARCH_MODULE_PATH = (
        Path(__file__).resolve().parents[4] / "src" / "api" / "endpoints" / "content" / "search.py"
    )

    @pytest.fixture()
    def search_source(self) -> str:
        """Read the full source of the search endpoint module."""
        return self.SEARCH_MODULE_PATH.read_text(encoding="utf-8")

    def test_no_mock_embedding_service(self, search_source: str) -> None:
        """MockEmbeddingService must NOT appear in search.py."""
        assert (
            "MockEmbeddingService" not in search_source
        ), "search.py contains 'MockEmbeddingService' — use Endpoints.get_embedding_service() instead"

    def test_no_mock_intent_classifier(self, search_source: str) -> None:
        """MockIntentClassifier must NOT appear in search.py."""
        assert (
            "MockIntentClassifier" not in search_source
        ), "search.py contains 'MockIntentClassifier' — use Endpoints.get_intent_classifier() instead"

    def test_no_inline_mock_class(self, search_source: str) -> None:
        """Inline 'class Mock' definitions must NOT appear in search.py."""
        assert (
            "class Mock" not in search_source
        ), "search.py contains inline 'class Mock' — inject real services via Endpoints registry"


# ── Task 2.2: EmbeddingService dependency injection ────────────────────


class TestEmbeddingServiceDependencyInjection:
    """Verify that the Endpoints registry exposes an embedding service getter."""

    def test_endpoints_has_get_embedding_service(self) -> None:
        """Endpoints class must have a get_embedding_service method."""
        from api.endpoints.deps_registry import Endpoints

        assert hasattr(Endpoints, "get_embedding_service"), (
            "Endpoints class is missing 'get_embedding_service' method — "
            "add it so search endpoints can obtain a real EmbeddingService"
        )

    def test_get_embedding_service_is_callable(self) -> None:
        """get_embedding_service must be a callable method, not a plain attribute."""
        from api.endpoints.deps_registry import Endpoints

        method = Endpoints.get_embedding_service
        assert callable(method), "'get_embedding_service' on Endpoints must be a callable method"


# ── Task 2.3: IntentClassifier dependency injection ────────────────────


class TestIntentClassifierDependencyInjection:
    """Verify that the Endpoints registry exposes an intent classifier getter."""

    def test_endpoints_has_get_intent_classifier(self) -> None:
        """Endpoints class must have a get_intent_classifier method."""
        from api.endpoints.deps_registry import Endpoints

        assert hasattr(Endpoints, "get_intent_classifier"), (
            "Endpoints class is missing 'get_intent_classifier' method — "
            "add it so search endpoints can obtain a real IntentClassifier"
        )

    def test_get_intent_classifier_is_callable(self) -> None:
        """get_intent_classifier must be a callable method, not a plain attribute."""
        from api.endpoints.deps_registry import Endpoints

        method = Endpoints.get_intent_classifier
        assert callable(method), "'get_intent_classifier' on Endpoints must be a callable method"

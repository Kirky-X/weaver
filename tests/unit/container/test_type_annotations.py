# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for Container type annotations.

Verifies that key service accessors return specific types, not Any.
"""

from __future__ import annotations

import inspect

from src.container.services import ContainerServicesMixin


class TestContainerTypeAnnotations:
    """Verify Container service methods have specific return types."""

    def test_graph_writer_return_type_not_any(self) -> None:
        """graph_writer() should return GraphWriter | None, not Any | None."""
        sig = inspect.signature(ContainerServicesMixin.graph_writer)
        return_annotation = sig.return_annotation
        assert return_annotation != inspect.Parameter.empty
        # The return type should be a string "GraphWriter | None" (from __future__ annotations)
        type_str = str(return_annotation)
        assert "GraphWriter" in type_str, f"Expected GraphWriter in return type, got: {type_str}"
        assert "Any" not in type_str, f"Return type should not contain Any, got: {type_str}"

    def test_graph_writer_attribute_type_not_any(self) -> None:
        """_graph_writer attribute should be typed as GraphWriter | None, not Any."""
        annotations = ContainerServicesMixin.__annotations__
        attr_type = annotations.get("_graph_writer", "Any")
        type_str = str(attr_type)
        assert (
            "GraphWriter" in type_str
        ), f"Expected GraphWriter in _graph_writer type, got: {type_str}"
        assert "Any" not in type_str, f"_graph_writer type should not contain Any, got: {type_str}"

    def test_memory_service_attribute_type_not_any(self) -> None:
        """_memory_service attribute should be typed as MemoryIntegrationService | None, not Any."""
        annotations = ContainerServicesMixin.__annotations__
        attr_type = annotations.get("_memory_service", "Any")
        type_str = str(attr_type)
        assert (
            "MemoryIntegrationService" in type_str
        ), f"Expected MemoryIntegrationService in _memory_service type, got: {type_str}"
        assert (
            "Any" not in type_str
        ), f"_memory_service type should not contain Any, got: {type_str}"

    def test_no_duplicate_get_embedding_model_id(self) -> None:
        """_get_embedding_model_id should only exist in services.py, not lifecycle.py."""
        from src.container import lifecycle

        assert not hasattr(
            lifecycle.ContainerLifecycleMixin, "_get_embedding_model_id"
        ), "_get_embedding_model_id should not exist in ContainerLifecycleMixin (use services.py version)"

    def test_get_embedding_model_id_in_services(self) -> None:
        """_get_embedding_model_id should exist in services.py."""
        assert hasattr(
            ContainerServicesMixin, "_get_embedding_model_id"
        ), "_get_embedding_model_id should exist in ContainerServicesMixin"

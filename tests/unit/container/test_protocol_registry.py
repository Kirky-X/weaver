# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for Protocol → implementation binding registry."""

from unittest.mock import MagicMock, patch

import pytest


class TestProtocolBindings:
    """PROTOCOL_BINDINGS structure and completeness."""

    def test_bindings_count(self):
        """Registry has 15 bindings (all container-managed protocols)."""
        from container.protocol_registry import PROTOCOL_BINDINGS

        assert len(PROTOCOL_BINDINGS) == 15

    def test_all_bindings_are_tuples(self):
        """Every binding is a (Protocol, accessor_name) tuple."""
        from container.protocol_registry import PROTOCOL_BINDINGS

        for protocol, accessor in PROTOCOL_BINDINGS:
            assert isinstance(protocol, type), f"{protocol} is not a type"
            assert isinstance(accessor, str), f"{accessor} is not a str"
            assert getattr(protocol, "_is_protocol", False), (
                f"{protocol.__name__} is not a Protocol"
            )

    def test_no_duplicate_accessors(self):
        """Each accessor name appears at most once."""
        from container.protocol_registry import PROTOCOL_BINDINGS

        accessors = [accessor for _, accessor in PROTOCOL_BINDINGS]
        assert len(accessors) == len(set(accessors))

    def test_known_unregistered_does_not_overlap_bindings(self):
        """KNOWN_UNREGISTERED names don't appear in PROTOCOL_BINDINGS."""
        from container.protocol_registry import KNOWN_UNREGISTERED, PROTOCOL_BINDINGS

        bound_names = {protocol.__name__ for protocol, _ in PROTOCOL_BINDINGS}
        overlap = bound_names & KNOWN_UNREGISTERED
        assert not overlap, f"Overlap between bindings and KNOWN_UNREGISTERED: {overlap}"


class TestAllDefinedProtocols:
    """all_defined_protocols() discovery."""

    def test_returns_set_of_strings(self):
        from container.protocol_registry import all_defined_protocols

        result = all_defined_protocols()
        assert isinstance(result, set)
        assert all(isinstance(name, str) for name in result)

    def test_includes_core_protocols(self):
        from container.protocol_registry import all_defined_protocols

        names = all_defined_protocols()
        expected = {
            "RelationalPool",
            "GraphPool",
            "CachePool",
            "ArticleRepository",
            "VectorRepository",
            "EntityRepository",
            "GraphWriter",
            "PipelineService",
        }
        assert expected.issubset(names)

    def test_excludes_non_protocols(self):
        """Non-Protocol exports (dataclasses, enums, functions) are excluded."""
        from container.protocol_registry import all_defined_protocols

        names = all_defined_protocols()
        assert "assert_implements" not in names
        assert "BingSearchResult" not in names
        assert "PersistStatus" not in names


class TestValidateProtocolBindings:
    """validate_protocol_bindings() runtime validation."""

    def test_valid_container_passes(self):
        """A mock container satisfying all bindings passes without error."""
        from container.protocol_registry import PROTOCOL_BINDINGS, validate_protocol_bindings

        container = MagicMock()
        for _, accessor in PROTOCOL_BINDINGS:
            getattr(container, accessor).return_value = MagicMock()

        # Patch assert_implements to no-op (MagicMock signatures don't match)
        with patch("container.protocol_registry.assert_implements"):
            validate_protocol_bindings(container)

    def test_none_return_skipped(self):
        """Accessors returning None are skipped (optional backends)."""
        from container.protocol_registry import PROTOCOL_BINDINGS, validate_protocol_bindings

        container = MagicMock()
        for _, accessor in PROTOCOL_BINDINGS:
            getattr(container, accessor).return_value = None

        # Should not raise (no assert_implements called)
        validate_protocol_bindings(container)

    def test_missing_accessor_reported(self):
        """Container without expected accessor produces problems."""
        from container.protocol_registry import validate_protocol_bindings

        container = MagicMock(spec=[])  # No attributes at all

        with pytest.raises(AssertionError, match="Protocol contract validation failed"):
            validate_protocol_bindings(container)

    def test_unregistered_protocols_returned(self):
        """All defined protocols are either bound or KNOWN_UNREGISTERED."""
        from container.protocol_registry import PROTOCOL_BINDINGS, validate_protocol_bindings

        container = MagicMock()
        for _, accessor in PROTOCOL_BINDINGS:
            getattr(container, accessor).return_value = MagicMock()

        with patch("container.protocol_registry.assert_implements"):
            unregistered = validate_protocol_bindings(container)

        # All 21 protocols are either in PROTOCOL_BINDINGS (15) or KNOWN_UNREGISTERED (6)
        assert isinstance(unregistered, list)
        assert len(unregistered) == 0, f"Unexpected unregistered: {unregistered}"


class TestImportSmoke:
    """Module imports without errors."""

    def test_protocol_registry_importable(self):
        from container.protocol_registry import (
            KNOWN_UNREGISTERED,
            PROTOCOL_BINDINGS,
            all_defined_protocols,
            validate_protocol_bindings,
        )

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for graph visualization endpoint security."""

import pytest


def test_hops_whitelist_mapping():
    """Verify hop patterns are correctly mapped."""
    from api.endpoints.graph_visualization import _HOPS_PATTERNS

    assert _HOPS_PATTERNS[1] == "*1..1"
    assert _HOPS_PATTERNS[2] == "*1..2"
    assert _HOPS_PATTERNS[3] == "*1..3"
    assert _HOPS_PATTERNS[4] == "*1..4"


def test_hops_whitelist_prevents_injection():
    """Verify that invalid hop values use safe default."""
    from api.endpoints.graph_visualization import _HOPS_PATTERNS

    # Invalid values should not be in whitelist
    assert 0 not in _HOPS_PATTERNS
    assert 5 not in _HOPS_PATTERNS
    assert -1 not in _HOPS_PATTERNS

    # get() returns None for invalid keys (default is "*1..2")
    assert _HOPS_PATTERNS.get(0) is None
    assert _HOPS_PATTERNS.get(5) is None
    assert _HOPS_PATTERNS.get(-1) is None


def test_hops_pattern_format():
    """Verify hop patterns use correct Cypher syntax."""
    from api.endpoints.graph_visualization import _HOPS_PATTERNS

    for hops, pattern in _HOPS_PATTERNS.items():
        # Pattern should start with * and contain range
        assert pattern.startswith("*")
        assert ".." in pattern
        # Range should match the key
        expected_range = f"1..{hops}"
        assert expected_range in pattern

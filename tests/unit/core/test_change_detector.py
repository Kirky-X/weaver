# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ChangeDetector: content hashing and update decision logic."""

from __future__ import annotations

import pytest

from core.change_detector import ChangeDetector


class TestComputeHash:
    """Tests for ChangeDetector.compute_hash."""

    def test_deterministic(self) -> None:
        """Same input produces same hash."""
        article = {"title": "Breaking News", "body": "Something happened."}
        h1 = ChangeDetector.compute_hash(article)
        h2 = ChangeDetector.compute_hash(article)
        assert h1 == h2

    def test_different_content_different_hash(self) -> None:
        """Different title/body produces different hash."""
        a1 = {"title": "Title A", "body": "Body A"}
        a2 = {"title": "Title B", "body": "Body A"}
        assert ChangeDetector.compute_hash(a1) != ChangeDetector.compute_hash(a2)

    def test_body_change_changes_hash(self) -> None:
        """Body change produces different hash."""
        a1 = {"title": "Same", "body": "Original"}
        a2 = {"title": "Same", "body": "Updated"}
        assert ChangeDetector.compute_hash(a1) != ChangeDetector.compute_hash(a2)

    def test_missing_fields_use_empty(self) -> None:
        """Missing title/body treated as empty string."""
        a1 = {"title": "", "body": ""}
        a2: dict[str, str] = {}
        assert ChangeDetector.compute_hash(a1) == ChangeDetector.compute_hash(a2)

    def test_hash_length_64(self) -> None:
        """SHA-256 hex digest is 64 characters."""
        h = ChangeDetector.compute_hash({"title": "x", "body": "y"})
        assert len(h) == 64

    def test_hash_is_hex(self) -> None:
        """Hash contains only hex characters."""
        h = ChangeDetector.compute_hash({"title": "x", "body": "y"})
        assert all(c in "0123456789abcdef" for c in h)


class TestNeedsUpdate:
    """Tests for ChangeDetector.needs_update."""

    def test_content_hash_changed(self) -> None:
        """Content hash difference triggers update."""
        existing = {"content_hash": "aaa"}
        incoming = {"content_hash": "bbb"}
        assert ChangeDetector.needs_update(existing, incoming) is True

    def test_content_hash_same(self) -> None:
        """Same content hash means no update needed."""
        existing = {"content_hash": "same"}
        incoming = {"content_hash": "same"}
        assert ChangeDetector.needs_update(existing, incoming) is False

    def test_force_reprocess(self) -> None:
        """force_reprocess=True triggers update even with same hash."""
        existing = {"content_hash": "same"}
        incoming = {"content_hash": "same", "force_reprocess": True}
        assert ChangeDetector.needs_update(existing, incoming) is True

    def test_retry_count_increased(self) -> None:
        """Higher retry_count triggers update."""
        existing = {"content_hash": "same", "retry_count": 0}
        incoming = {"content_hash": "same", "retry_count": 1}
        assert ChangeDetector.needs_update(existing, incoming) is True

    def test_retry_count_same(self) -> None:
        """Same retry_count with same hash means no update."""
        existing = {"content_hash": "same", "retry_count": 2}
        incoming = {"content_hash": "same", "retry_count": 2}
        assert ChangeDetector.needs_update(existing, incoming) is False

    def test_existing_no_hash_incoming_has_hash(self) -> None:
        """Existing has no content_hash but incoming does triggers update."""
        existing: dict[str, str | None] = {"content_hash": None}
        incoming = {"content_hash": "abc"}
        assert ChangeDetector.needs_update(existing, incoming) is True

    def test_both_no_hash(self) -> None:
        """Both have no content_hash means no update."""
        existing: dict[str, str | None] = {"content_hash": None}
        incoming: dict[str, str | None] = {"content_hash": None}
        assert ChangeDetector.needs_update(existing, incoming) is False


class TestDetectChangedFields:
    """Tests for ChangeDetector.detect_changed_fields."""

    def test_title_changed(self) -> None:
        """Detect title change."""
        existing = {"title": "Old Title", "body": "Same body", "category": "tech"}
        incoming = {"title": "New Title", "body": "Same body", "category": "tech"}
        changed = ChangeDetector.detect_changed_fields(existing, incoming)
        assert "title" in changed

    def test_body_changed(self) -> None:
        """Detect body change."""
        existing = {"title": "Same", "body": "Old body", "category": "tech"}
        incoming = {"title": "Same", "body": "New body", "category": "tech"}
        changed = ChangeDetector.detect_changed_fields(existing, incoming)
        assert "body" in changed

    def test_category_changed(self) -> None:
        """Detect category change."""
        existing = {"title": "Same", "body": "Same", "category": "tech"}
        incoming = {"title": "Same", "body": "Same", "category": "politics"}
        changed = ChangeDetector.detect_changed_fields(existing, incoming)
        assert "category" in changed

    def test_no_changes(self) -> None:
        """No changes returns empty list."""
        existing = {"title": "Same", "body": "Same", "category": "tech"}
        incoming = {"title": "Same", "body": "Same", "category": "tech"}
        changed = ChangeDetector.detect_changed_fields(existing, incoming)
        assert changed == []

    def test_multiple_changes(self) -> None:
        """Detect multiple field changes."""
        existing = {"title": "Old", "body": "Old", "category": "tech"}
        incoming = {"title": "New", "body": "New", "category": "politics"}
        changed = ChangeDetector.detect_changed_fields(existing, incoming)
        assert set(changed) == {"title", "body", "category"}

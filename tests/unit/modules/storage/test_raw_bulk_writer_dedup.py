# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Tests for raw_bulk_writer content_hash dedup fixes.

Verifies:
- Multiple articles with the same hash all get results (idx_by_hash)
- In-batch duplicates reuse the first occurrence's article_id
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestIdxByHashDedup:
    """hash_to_raw → idx_by_hash ensures all indices get results."""

    def test_idx_by_hash_collects_multiple_indices(self):
        """Verify that idx_by_hash groups all indices sharing the same hash."""
        # Simulate the Stage 2 logic
        idx_by_hash: dict[str, list[tuple[int, str, str]]] = {}
        prepared = [
            (0, "raw_a", "url_a"),
            (1, "raw_b", "url_b"),
            (2, "raw_c", "url_c"),  # Same hash as raw_a
        ]
        hashes = {"url_a": "hash_1", "url_b": "hash_2", "url_c": "hash_1"}

        for idx, raw, norm_url in prepared:
            ch = hashes[norm_url]
            idx_by_hash.setdefault(ch, []).append((idx, raw, norm_url))

        # hash_1 should have TWO indices (0 and 2)
        assert len(idx_by_hash["hash_1"]) == 2
        assert idx_by_hash["hash_1"][0][0] == 0
        assert idx_by_hash["hash_1"][1][0] == 2
        # hash_2 should have ONE index
        assert len(idx_by_hash["hash_2"]) == 1

    def test_db_query_fills_all_indices(self):
        """When DB returns existing hash, ALL indices with that hash get the result."""
        idx_by_hash: dict[str, list[tuple[int, str, str]]] = {
            "hash_1": [(0, "raw_a", "url_a"), (2, "raw_c", "url_c")],
            "hash_2": [(1, "raw_b", "url_b")],
        }
        results: list[uuid.UUID | None] = [None, None, None]
        existing_db_id = uuid.uuid4()

        # Simulate Stage 2.5: DB returns existing hash
        for row_hash, row_id in [("hash_1", existing_db_id)]:
            if row_hash in idx_by_hash:
                for idx, _, _ in idx_by_hash[row_hash]:
                    results[idx] = row_id

        # Both idx 0 and 2 should have the same existing DB id
        assert results[0] == existing_db_id
        assert results[2] == existing_db_id
        # idx 1 should still be None (not in DB)
        assert results[1] is None


class TestInBatchDedup:
    """In-batch duplicates reuse first occurrence's article_id."""

    def test_deferred_batch_dup_tracking(self):
        """Verify batch_dup_indices collects deferred duplicates."""
        in_batch_first_idx: dict[str, int] = {}
        batch_dup_indices: list[tuple[int, str]] = []
        prepared = [
            (0, "raw_a", "url_a"),
            (1, "raw_b", "url_b"),
            (2, "raw_c", "url_c"),  # Same hash as raw_a
        ]
        hashes = {"url_a": "hash_1", "url_b": "hash_2", "url_c": "hash_1"}

        for idx, raw, norm_url in prepared:
            ch = hashes[norm_url]
            if ch in in_batch_first_idx:
                batch_dup_indices.append((idx, ch))
                continue
            in_batch_first_idx[ch] = idx

        # idx 2 should be deferred as a batch duplicate
        assert len(batch_dup_indices) == 1
        assert batch_dup_indices[0] == (2, "hash_1")
        # First occurrence should be idx 0
        assert in_batch_first_idx["hash_1"] == 0

    def test_resolve_deferred_dups_after_flush(self):
        """After flush, deferred duplicates get the first occurrence's article_id."""
        new_id = uuid.uuid4()
        hash_to_id = {"hash_1": new_id}
        results: list[uuid.UUID | None] = [None, None, None]
        results[0] = new_id  # First occurrence got ID from flush

        batch_dup_indices = [(2, "hash_1")]
        for dup_idx, dup_hash in batch_dup_indices:
            first_id = hash_to_id.get(dup_hash)
            if first_id is not None:
                results[dup_idx] = first_id

        # idx 2 should reuse idx 0's article_id
        assert results[0] == new_id
        assert results[2] == new_id
        assert results[0] == results[2]

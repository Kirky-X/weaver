#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for scripts/dedup_article_graph.py migration script.

Tests the Article graph node deduplication migration that cleans up
residual business fields (title, category, publish_time, score) from
Article nodes in both Neo4j and LadybugDB backends, after the
T025-T030 Article node slim-down (design.md §D2).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add scripts/ to path for importing dedup_article_graph module
_scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import dedup_article_graph


class TestBackupArticleFields:
    """Tests for backup_article_fields function."""

    @pytest.mark.asyncio
    async def test_backup_article_fields_writes_json(self, tmp_path):
        """Test that backup function correctly queries Article nodes and writes JSON.

        Verifies:
        - Query executes correct Cypher (MATCH (a:Article) RETURN ...)
        - JSON file contains all Article nodes with legacy fields
        - Atomic write (temp file + os.replace)
        - Temp file is cleaned up after rename
        """
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "graph-1",
                    "pg_id": "pg-uuid-1",
                    "title": "Test Article 1",
                    "category": "tech",
                    "publish_time": 1234567890,
                    "score": 0.95,
                },
                {
                    "id": "graph-2",
                    "pg_id": "pg-uuid-2",
                    "title": None,
                    "category": None,
                    "publish_time": None,
                    "score": None,
                },
            ]
        )

        backup_path = str(tmp_path / "article_fields_backup.json")

        result = await dedup_article_graph.backup_article_fields(mock_pool, backup_path)

        # Verify query was called
        mock_pool.execute_query.assert_called_once()
        query = mock_pool.execute_query.call_args[0][0]
        assert "MATCH (a:Article)" in query
        assert "RETURN" in query
        assert "title" in query
        assert "category" in query
        assert "publish_time" in query
        assert "score" in query

        # Verify result contains the articles
        assert len(result) == 2
        assert result[0]["id"] == "graph-1"
        assert result[0]["title"] == "Test Article 1"

        # Verify JSON file was written
        assert os.path.exists(backup_path)
        with open(backup_path) as f:
            data = json.load(f)
        assert "articles" in data
        assert len(data["articles"]) == 2
        assert data["articles"][0]["id"] == "graph-1"
        assert data["articles"][0]["title"] == "Test Article 1"

        # Verify temp file was cleaned up (atomic write)
        assert not os.path.exists(backup_path + ".tmp")


class TestLadybugDropColumn:
    """Tests for cleanup_ladybug function (idempotent DROP COLUMN)."""

    @pytest.mark.asyncio
    async def test_ladybug_drop_column_idempotent(self):
        """Test that DROP COLUMN doesn't raise when column doesn't exist.

        Verifies:
        - Each DROP COLUMN is wrapped in try/except
        - Non-existent columns are silently ignored (idempotent)
        - Function returns count of successfully dropped columns
        """
        mock_pool = MagicMock()
        # Simulate: title and publish_time dropped successfully,
        # category and score fail (already dropped)
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # DROP COLUMN title - success
                Exception("Column category does not exist"),  # failure
                [],  # DROP COLUMN publish_time - success
                Exception("Column score does not exist"),  # failure
            ]
        )

        result = await dedup_article_graph.cleanup_ladybug(mock_pool)

        # Should not raise an error
        # Should return count of successfully dropped columns (2)
        assert result == 2
        # Should have attempted all 4 columns
        assert mock_pool.execute_query.call_count == 4

        # Verify correct ALTER TABLE statements
        for i, call in enumerate(mock_pool.execute_query.call_args_list):
            query = call[0][0]
            assert "ALTER TABLE Article DROP COLUMN" in query
            field = dedup_article_graph.LEGACY_FIELDS[i]
            assert field in query


class TestNeo4jRemoveProperties:
    """Tests for cleanup_neo4j function (REMOVE properties)."""

    @pytest.mark.asyncio
    async def test_neo4j_remove_properties_executes_cypher(self):
        """Test that REMOVE properties executes correct Cypher.

        Verifies:
        - Count query is executed first to get modified node count
        - REMOVE query uses exact Cypher from task spec
        - Function returns count of nodes that had legacy properties
        """
        mock_pool = MagicMock()
        # First call: count query returns 5 nodes with legacy fields
        # Second call: REMOVE query returns empty list
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [{"modified_count": 5}],  # count query
                [],  # REMOVE query
            ]
        )

        result = await dedup_article_graph.cleanup_neo4j(mock_pool)

        # Should return the modified node count
        assert result == 5

        # Should have made 2 calls (count + REMOVE)
        assert mock_pool.execute_query.call_count == 2

        # Verify count query
        count_query = mock_pool.execute_query.call_args_list[0][0][0]
        assert "MATCH (a:Article)" in count_query
        assert "count" in count_query.lower()

        # Verify REMOVE query uses exact Cypher from task spec
        remove_query = mock_pool.execute_query.call_args_list[1][0][0]
        assert (
            "MATCH (a:Article) REMOVE a.title, a.category, a.publish_time, a.score" in remove_query
        )


class TestDryRunMode:
    """Tests for --dry-run mode."""

    @pytest.mark.asyncio
    async def test_dry_run_does_not_modify_db(self, tmp_path):
        """Test that --dry-run mode doesn't execute any cleanup queries.

        Verifies:
        - Backup is still performed (read-only operation)
        - No ALTER TABLE or REMOVE queries are executed
        - Only backup query (MATCH ... RETURN) is executed
        """
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "graph-1",
                    "pg_id": "pg-uuid-1",
                    "title": "Test Article",
                    "category": "tech",
                    "publish_time": 1234567890,
                    "score": 0.95,
                },
            ]
        )

        backup_path = str(tmp_path / "article_fields_backup.json")

        result = await dedup_article_graph.migrate(
            pool=mock_pool,
            pool_type="ladybug",
            backup_path=backup_path,
            yes=True,
            dry_run=True,
        )

        # Verify only backup query was executed (no cleanup queries)
        assert mock_pool.execute_query.call_count == 1
        query = mock_pool.execute_query.call_args_list[0][0][0]
        assert "MATCH (a:Article)" in query
        assert "RETURN" in query
        # No ALTER TABLE or REMOVE queries
        for call in mock_pool.execute_query.call_args_list:
            query = call[0][0]
            assert "ALTER TABLE" not in query
            assert "REMOVE" not in query

        # Verify result indicates dry run
        assert result["dry_run"] is True
        assert result["cancelled"] is False


class TestYesFlag:
    """Tests for --yes flag (skips confirmation)."""

    def test_yes_flag_skips_confirmation(self):
        """Test that --yes flag skips input() confirmation.

        Verifies:
        - input() is not called when yes=True
        - Function returns True immediately
        """
        with patch("builtins.input") as mock_input:
            result = dedup_article_graph.confirm_proceed(
                impact={"backup_count": 10, "pool_type": "ladybug"},
                yes=True,
            )

            # Verify input() was not called
            mock_input.assert_not_called()
            # Verify function returns True
            assert result is True

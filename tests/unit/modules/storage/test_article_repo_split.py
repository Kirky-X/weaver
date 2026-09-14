# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T022: ArticleReader / ArticleWriter / RawBulkWriter split contract."""

from unittest.mock import MagicMock

from modules.storage.postgres.article_reader import ArticleReader
from modules.storage.postgres.article_repo import ArticleRepo
from modules.storage.postgres.article_writer import ArticleWriter
from modules.storage.postgres.raw_bulk_writer import RawBulkWriter


class TestSplitContract:
    def test_reader_holds_pool(self):
        pool = MagicMock()
        reader = ArticleReader(pool)
        assert reader._pool is pool

    def test_writer_holds_pool(self):
        pool = MagicMock()
        writer = ArticleWriter(pool)
        assert writer._pool is pool

    def test_raw_bulk_writer_holds_pool(self):
        pool = MagicMock()
        writer = RawBulkWriter(pool)
        assert writer._pool is pool

    def test_facade_composes_three_halves(self):
        pool = MagicMock()
        repo = ArticleRepo(pool)
        assert isinstance(repo._reader, ArticleReader)
        assert isinstance(repo._writer, ArticleWriter)
        assert isinstance(repo._raw_bulk, RawBulkWriter)
        assert repo._reader._pool is pool
        assert repo._writer._pool is pool
        assert repo._raw_bulk._pool is pool

    def test_reader_exposes_no_write_methods(self):
        reader_methods = {m for m in dir(ArticleReader) if not m.startswith("_")}
        write_only = {"upsert", "bulk_upsert", "mark_failed", "update_persist_status", "insert_raw"}
        assert not reader_methods & write_only

    def test_writer_exposes_no_bulk_raw_methods(self):
        writer_methods = {m for m in dir(ArticleWriter) if not m.startswith("_")}
        assert "bulk_insert_raw" not in writer_methods

    def test_facade_public_surface_unchanged(self):
        facade = {m for m in dir(ArticleRepo) if not m.startswith("_")}
        expected = {
            "get",
            "get_by_id",
            "get_by_ids",
            "get_existing_urls",
            "get_existing_titles",
            "get_pending",
            "get_pending_neo4j",
            "get_stuck_articles",
            "get_all_article_ids",
            "get_incomplete_articles",
            "get_failed_articles",
            "fetch_titles_by_pg_ids",
            "fetch_bodies_by_pg_ids",
            "get_task_progress_stats",
            "search_by_text",
            "detect_merge_cycle",
            "resolve_final_merge_target",
            "bulk_upsert",
            "upsert",
            "update_persist_status",
            "mark_terminal_by_url",
            "update_credibility",
            "requeue_processing",
            "revert_to_pg_done",
            "update_enrichment_if_null",
            "update_processing_stage",
            "bulk_update_processing_stage",
            "mark_failed",
            "mark_processing",
            "revert_to_stored",
            "deduplicate_articles",
            "insert_raw",
            "bulk_insert_raw",
        }
        assert expected <= facade

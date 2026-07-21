# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Test FK references point to articles_core table, not articles VIEW.

Validates GAP-H05 fix: LLMFailureRecord, PendingSync, and
DailyBriefingItem article_id FKs reference the physical table
articles_core instead of the articles VIEW.
"""

from core.db.models import DailyBriefingItem, LLMFailureRecord, PendingSync


class TestFKIntegrity:
    """Verify article_id FK references point to articles_core."""

    def test_llm_failure_record_article_id_fk_references_articles_core(self) -> None:
        """LLMFailureRecord.article_id FK should reference articles_core.id."""
        col = LLMFailureRecord.__table__.c.article_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1, f"Expected 1 FK, got {len(fks)}"
        fk = fks[0]
        assert str(fk.target_fullname) == "articles_core.id", (
            f"Expected FK to articles_core.id, got {fk.target_fullname}"
        )

    def test_llm_failure_record_article_id_ondelete_set_null(self) -> None:
        """LLMFailureRecord.article_id FK should have ondelete=SET NULL."""
        col = LLMFailureRecord.__table__.c.article_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.ondelete == "SET NULL", f"Expected ondelete SET NULL, got {fk.ondelete}"

    def test_pending_sync_article_id_fk_references_articles_core(self) -> None:
        """PendingSync.article_id FK should reference articles_core.id."""
        col = PendingSync.__table__.c.article_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1, f"Expected 1 FK, got {len(fks)}"
        fk = fks[0]
        assert str(fk.target_fullname) == "articles_core.id", (
            f"Expected FK to articles_core.id, got {fk.target_fullname}"
        )

    def test_pending_sync_article_id_ondelete_cascade(self) -> None:
        """PendingSync.article_id FK should have ondelete=CASCADE."""
        col = PendingSync.__table__.c.article_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.ondelete == "CASCADE", f"Expected ondelete CASCADE, got {fk.ondelete}"

    def test_daily_briefing_item_article_id_fk_references_articles_core(self) -> None:
        """DailyBriefingItem.article_id FK should reference articles_core.id."""
        col = DailyBriefingItem.__table__.c.article_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1, f"Expected 1 FK, got {len(fks)}"
        fk = fks[0]
        assert str(fk.target_fullname) == "articles_core.id", (
            f"Expected FK to articles_core.id, got {fk.target_fullname}"
        )

    def test_daily_briefing_item_article_id_ondelete_cascade(self) -> None:
        """DailyBriefingItem.article_id FK should have ondelete=CASCADE."""
        col = DailyBriefingItem.__table__.c.article_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.ondelete == "CASCADE", f"Expected ondelete CASCADE, got {fk.ondelete}"

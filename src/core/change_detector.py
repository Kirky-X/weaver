# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Change detection for article incremental updates.

Implements: Weaver-数据库设计文档 §9.11.3
"""

from __future__ import annotations

import hashlib


class ChangeDetector:
    """Detect whether article content has truly changed, avoiding unnecessary updates."""

    # Fields to compare for change detection
    TRACKED_FIELDS: list[str] = ["title", "body", "category"]

    @staticmethod
    def compute_hash(article: dict) -> str:
        """Compute SHA-256 hash based on title + body.

        Args:
            article: Dict with at least 'title' and 'body' keys.

        Returns:
            Hex digest of SHA-256 hash (64 characters).
        """
        content = f"{article.get('title', '')}|{article.get('body', '')}"
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def needs_update(existing: dict, incoming: dict) -> bool:
        """Determine if an article needs to be updated.

        Args:
            existing: Current article data from database.
            incoming: New article data from pipeline.

        Returns:
            True if the article should be updated.
        """
        # 1. Content hash differs → needs update
        if existing.get("content_hash") != incoming.get("content_hash"):
            return True
        # 2. Force reprocess → update even with same content
        if incoming.get("force_reprocess"):
            return True
        # 3. Retry count increased → retry pipeline
        return incoming.get("retry_count", 0) > existing.get("retry_count", 0)

    @classmethod
    def detect_changed_fields(cls, existing: dict, incoming: dict) -> list[str]:
        """Detect which tracked fields have changed between existing and incoming.

        Args:
            existing: Current article data from database.
            incoming: New article data from pipeline.

        Returns:
            List of field names that differ.
        """
        changed: list[str] = []
        for field in cls.TRACKED_FIELDS:
            if existing.get(field) != incoming.get(field):
                changed.append(field)
        return changed

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Category diversity constraint for briefing generation."""

from __future__ import annotations

from collections import Counter
from typing import Any


class CategoryDiversity:
    """Ensure category diversity in briefing selections."""

    def __init__(self, max_per_category: int = 3):
        self._max_per_category = max_per_category

    def apply(
        self,
        articles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Filter articles to ensure category diversity.

        At most max_per_category articles per category are kept.
        Articles are assumed to be pre-sorted by score (descending).

        Args:
            articles: Pre-scored and sorted articles.

        Returns:
            Filtered articles with category diversity enforced.
        """
        selected = []
        category_count: Counter = Counter()

        for article in articles:
            cat = article.get("category") or "unknown"
            if category_count[cat] < self._max_per_category:
                selected.append(article)
                category_count[cat] += 1
            if len(selected) >= 10:
                break

        return selected

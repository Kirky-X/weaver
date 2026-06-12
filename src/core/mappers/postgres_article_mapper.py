from typing import Any

from core.models.shared import ArticleView


class PostgresArticleMapper:
    """Maps PostgreSQL ORM rows to ArticleView with field-level type conversion.

    Implements: Data Contract Layer — PostgresArticleMapper
    """

    @staticmethod
    def to_view(orm_row: Any) -> ArticleView:
        if isinstance(orm_row, dict):
            data = orm_row
        else:
            data = {
                col: getattr(orm_row, col)
                for col in ArticleView.model_fields
                if hasattr(orm_row, col)
            }

        # Type conversion for numeric fields that may come as strings
        if "score" in data and data["score"] is not None:
            data["score"] = float(data["score"])
        if "sentiment_score" in data and data["sentiment_score"] is not None:
            data["sentiment_score"] = float(data["sentiment_score"])
        if "quality_score" in data and data["quality_score"] is not None:
            data["quality_score"] = float(data["quality_score"])
        if "credibility_score" in data and data["credibility_score"] is not None:
            data["credibility_score"] = float(data["credibility_score"])
        if "cross_verification" in data and data["cross_verification"] is not None:
            data["cross_verification"] = float(data["cross_verification"])

        # Default for verified_by_sources when missing
        if "verified_by_sources" not in data:
            data["verified_by_sources"] = 0

        return ArticleView.model_validate(data)

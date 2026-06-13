from typing import Any

from core.models.shared import ArticleView


class PostgresArticleMapper:
    """Maps PostgreSQL ORM rows to ArticleView with field-level type conversion.

    Implements: MapperProtocol
    """

    def to_view(self, data: Any) -> ArticleView:
        if isinstance(data, dict):
            orm_row = data
        else:
            orm_row = {
                col: getattr(data, col) for col in ArticleView.model_fields if hasattr(data, col)
            }

        # Type conversion for numeric fields that may come as strings
        if "score" in orm_row and orm_row["score"] is not None:
            orm_row["score"] = float(orm_row["score"])
        if "sentiment_score" in orm_row and orm_row["sentiment_score"] is not None:
            orm_row["sentiment_score"] = float(orm_row["sentiment_score"])
        if "quality_score" in orm_row and orm_row["quality_score"] is not None:
            orm_row["quality_score"] = float(orm_row["quality_score"])
        if "credibility_score" in orm_row and orm_row["credibility_score"] is not None:
            orm_row["credibility_score"] = float(orm_row["credibility_score"])
        if "cross_verification" in orm_row and orm_row["cross_verification"] is not None:
            orm_row["cross_verification"] = float(orm_row["cross_verification"])

        # Default for verified_by_sources when missing
        if "verified_by_sources" not in orm_row:
            orm_row["verified_by_sources"] = 0

        return ArticleView.model_validate(orm_row)

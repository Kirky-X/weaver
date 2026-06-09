from typing import Any

from core.models.shared import ArticleView


class PostgresArticleMapper:
    @staticmethod
    def to_view(orm_row: Any) -> ArticleView:
        return ArticleView.model_validate(orm_row)

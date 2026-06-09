from typing import Any

from core.models.shared import EntityView


class Neo4jEntityMapper:
    @staticmethod
    def to_view(record: dict[str, Any]) -> EntityView:
        return EntityView.model_validate(record)

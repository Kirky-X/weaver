from datetime import datetime
from typing import Any

from core.models.shared import EntityView


class Neo4jEntityMapper:
    """Maps Neo4j records to EntityView with field-level mapping and type conversion.

    Implements: Data Contract Layer — Neo4jEntityMapper
    """

    @staticmethod
    def to_view(record: dict[str, Any]) -> EntityView:
        data = dict(record)

        # Type conversion for numeric fields that may come as strings
        if "confidence" in data and data["confidence"] is not None:
            data["confidence"] = float(data["confidence"])
        if "degree" in data and data["degree"] is not None:
            data["degree"] = int(data["degree"])

        # Convert last_mentioned string to datetime if needed
        if "last_mentioned" in data and isinstance(data["last_mentioned"], str):
            data["last_mentioned"] = datetime.fromisoformat(data["last_mentioned"])

        return EntityView.model_validate(data)

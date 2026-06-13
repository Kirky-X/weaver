from datetime import datetime
from typing import Any

from core.models.shared import EntityView


class Neo4jEntityMapper:
    """Maps Neo4j records to EntityView with field-level mapping and type conversion.

    Implements: MapperProtocol
    """

    def to_view(self, data: dict[str, Any]) -> EntityView:
        record = dict(data)

        # Type conversion for numeric fields that may come as strings
        if "confidence" in record and record["confidence"] is not None:
            record["confidence"] = float(record["confidence"])
        if "degree" in record and record["degree"] is not None:
            record["degree"] = int(record["degree"])

        # Convert last_mentioned string to datetime if needed
        if "last_mentioned" in record and isinstance(record["last_mentioned"], str):
            record["last_mentioned"] = datetime.fromisoformat(record["last_mentioned"])

        return EntityView.model_validate(record)

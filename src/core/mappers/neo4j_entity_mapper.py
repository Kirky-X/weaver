# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X

from datetime import datetime
from typing import Any

from core.models.shared import EntityView
from core.observability import get_logger

log = get_logger(__name__)


class Neo4jEntityMapper:
    """Maps Neo4j records to EntityView with field-level mapping and type conversion.

    Implements: MapperProtocol
    """

    def to_view(self, data: dict[str, Any]) -> EntityView:
        record = dict(data)

        # Type conversion for numeric fields that may come as strings.
        # A single corrupt record must not break the whole batch — fall
        # back to the EntityView defaults instead of raising.
        if "confidence" in record and record["confidence"] is not None:
            try:
                record["confidence"] = float(record["confidence"])
            except (TypeError, ValueError) as exc:
                log.warning(
                    "entity_confidence_conversion_failed",
                    value=repr(record["confidence"]),
                    error=str(exc),
                )
                record["confidence"] = 1.0
        if "degree" in record and record["degree"] is not None:
            try:
                record["degree"] = int(record["degree"])
            except (TypeError, ValueError) as exc:
                log.warning(
                    "entity_degree_conversion_failed",
                    value=repr(record["degree"]),
                    error=str(exc),
                )
                record["degree"] = 0

        # Convert last_mentioned string to datetime if needed; malformed
        # timestamps degrade to None instead of failing the mapping.
        if "last_mentioned" in record and isinstance(record["last_mentioned"], str):
            try:
                record["last_mentioned"] = datetime.fromisoformat(record["last_mentioned"])
            except ValueError as exc:
                log.warning(
                    "entity_last_mentioned_parse_failed",
                    value=record["last_mentioned"],
                    error=str(exc),
                )
                record["last_mentioned"] = None

        return EntityView.model_validate(record)

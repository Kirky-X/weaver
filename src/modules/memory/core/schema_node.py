# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""SchemaNode: Represents an abstracted pattern from event clusters.

A SchemaNode is created by the ConsolidationWorker when it identifies
recurring patterns across multiple events of the same type and with
overlapping participants.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SchemaNode:
    """Abstracted schema pattern from clustered events.

    Created by StructuralConsolidationWorker when it identifies recurring
    event patterns. Represents generalized knowledge extracted from
    specific event instances.

    Attributes:
        id: Unique identifier for the schema.
        event_type: The type of events this schema generalizes.
        pattern: The identified pattern (e.g., participant combination).
        confidence: Confidence score of the schema (0.0-1.0).
    """

    id: str
    event_type: str
    pattern: str
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")

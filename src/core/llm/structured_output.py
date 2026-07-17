# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Schema-driven structured output — SchemaNode → JSON Schema (T023 / R-structured-001).

SchemaDrivenStructuredOutput queries the graph database for a SchemaNode by
its business-level id (format: ``schema-{event_type}``) and converts it to a
JSON Schema dict ready for LLM ``response_format`` parameter.

SchemaNode schema (actual fields):
    - ``id`` (str, primary key, format "schema-{event_type}")
    - ``event_type`` (str, business key, e.g. "融资"/"政策发布")
    - ``pattern`` (str, JSON Schema string produced by SchemaExtractorNode)
    - ``confidence`` (float [0,1])
    - ``created_at`` / ``updated_at`` (timestamps)

Spec R-structured-001 field naming conflict (Rule 7 exposed):
    Spec mentions ``SchemaNode.properties`` and ``entity_type`` as the fields
    to convert. Actual SchemaNode schema uses ``pattern`` (already a complete
    JSON Schema string) and ``event_type`` (business key). Resolution:
    aligned with actual schema — ``pattern`` is parsed as JSON to produce
    the schema dict, and ``event_type`` is added as the JSON Schema ``title``
    field. The docstring of SchemaExtractorNode and the schema files
    (ladybug_schema.py L160-167) confirm ``pattern`` / ``event_type`` are
    the canonical field names. Updating the spec wording is out of scope for
    T023 (would require specmark converge phase 7).

Conversion rules:
    - ``pattern`` (JSON string) → ``json.loads`` → schema dict (R-structured-001)
    - ``event_type`` → schema["title"] (latest-wins: overrides any title
      embedded in ``pattern``, because event_type is the authoritative
      business key maintained by SchemaExtractorNode)
    - Returns ``{schema: dict, schema_node_id: str}``

Failure handling (Rule 12 — fail loud):
    - SchemaNode not found (empty result OR record missing ``pattern``)
      → raise ``SchemaNotFoundError`` (caller may regenerate via
      SchemaExtractorNode, or degrade to plain LLM call per R-structured-002).
    - Invalid JSON in ``pattern`` → propagate ``ValueError`` from
      ``json.loads``. Do not swallow — caller needs to know the SchemaNode
      is corrupted (Rule 12).
    - GraphPool exceptions propagate (Rule 12).

Cross-database compatibility (Neo4j + LadybugDB):
    The query uses standard Cypher ``MATCH`` + ``RETURN ... AS`` pattern
    that both Neo4j and LadybugDB (Kùzu) support. Unlike temporal queries
    in TrendDetector (which need ``pool.database_type == 'ladybug'``
    branches for INT64 epoch vs datetime()), SchemaNode fields are all
    plain strings/floats — no database-specific branch is needed here.

Constructor injection (Rule — Protocol type, not concrete class):
    ``__init__(self, graph_pool: GraphPool)`` accepts any pool implementing
    GraphPool (Neo4jPool / LadybugPool).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger(__name__)


class SchemaNotFoundError(Exception):
    """Raised when a SchemaNode cannot be found or is malformed.

    Spec R-structured-001: SchemaDrivenStructuredOutput raises this when
    the SchemaNode does not exist (empty query result) or lacks the
    ``pattern`` field (malformed record). Callers (T024 LLMClient.
    structured_call) catch this to degrade to a plain LLM call returning
    ``{_fallback: true, content: <llm_response>}`` (R-structured-002
    fallback contract).

    This is NOT a programming bug — it signals schema data absence. The
    caller is expected to catch this exception (R-structured-002 降级为
    普通调用). Propagating it would surface as a 500 to the API caller,
    which is incorrect — degradation is the intended behavior.

    Attributes:
        schema_node_id: The schema_node_id that was queried but not found.
    """

    def __init__(self, *, schema_node_id: str) -> None:
        self.schema_node_id = schema_node_id
        super().__init__(f"SchemaNode not found for schema_node_id={schema_node_id!r}")


class StructuredOutputValidationError(Exception):
    """Raised when LLM response cannot be reconciled with the JSON Schema.

    Spec R-structured-002 / R-structured-003: after ``structured_call``
    fetches the schema and calls the LLM with ``response_format``, the
    response must be validated against the schema. If validation fails
    after one retry (with a schema-violation hint prompt), this exception
    is raised carrying:

        - ``schema``: the JSON Schema dict that was used for validation
          (includes ``title``=event_type). Useful for debugging which
          field violated what constraint.
        - ``last_response``: the raw LLM response string from the final
          attempt (after retry). May be non-JSON or JSON that fails
          schema validation. Never None — at least one call was made.

    This exception is a programming/data-quality signal: either the LLM
    cannot satisfy the schema, or the schema is misconfigured, or the
    prompt is ambiguous. It MUST propagate to the caller (Rule 12) —
    silently swallowing it would mask the failure (3.25 behavior).

    Callers should:
        - Surface as a 500 / domain error (NOT 200 with fallback —
          R-structured-002 makes ``SchemaNotFoundError`` the ONLY
          trigger for fallback; validation failure is a hard error).
        - Log schema + last_response for debugging.
        - PII handling: ``last_response`` may contain user-content echoed
          by the LLM. When logging or persisting, apply the same redaction
          policy used for LLM request/response payloads elsewhere in the
          system. Never return ``last_response`` verbatim to API end users.
        - Consider regenerating the schema via SchemaExtractorNode if
          the schema is the root cause.

    Attributes:
        schema: JSON Schema dict that was used for validation.
        last_response: Raw LLM response string from the final attempt.
    """

    def __init__(self, *, schema: dict[str, Any], last_response: str) -> None:
        self.schema = schema
        self.last_response = last_response
        super().__init__(
            "Structured output validation failed after retry. "
            f"schema_title={schema.get('title')!r}, "
            f"last_response_len={len(last_response)}"
        )


class SchemaDrivenStructuredOutput:
    """Query SchemaNode and convert to JSON Schema for LLM structured output.

    Implements R-structured-001: queries the graph database for a SchemaNode
    by ``id`` and converts its ``pattern`` (JSON Schema string) +
    ``event_type`` (business key, used as JSON Schema title) into a dict
    suitable for LLM ``response_format`` parameter.

    The query is intentionally simple (single MATCH + RETURN AS) so it works
    identically on Neo4j and LadybugDB without dialect branching.

    Args:
        graph_pool: Any object implementing GraphPool Protocol
            (Neo4jPool / LadybugPool). Used to execute the SchemaNode query.

    Raises:
        SchemaNotFoundError: If SchemaNode does not exist or pattern is missing.
        ValueError: If ``pattern`` field contains invalid JSON or non-dict
            JSON value (e.g. ``null``). Propagated from ``json.loads`` —
            caller must handle (Rule 12 fail-loud).
        Exception: GraphPool exceptions propagate (Rule 12 fail-loud).
    """

    def __init__(self, graph_pool: GraphPool) -> None:
        self._pool = graph_pool

    async def get_schema(self, schema_node_id: str) -> dict[str, Any]:
        """Query SchemaNode by id and return {schema: dict, schema_node_id: str}.

        Args:
            schema_node_id: SchemaNode business-level id (format
                "schema-{event_type}", e.g. "schema-funding").

        Returns:
            Dict with two keys:
                - ``schema``: JSON Schema dict (parsed from SchemaNode.pattern,
                  with title=event_type).
                - ``schema_node_id``: The input schema_node_id (echoed for
                  caller tracking).

        Raises:
            SchemaNotFoundError: SchemaNode not found or pattern missing.
            ValueError: pattern field is invalid JSON or non-dict.
            Exception: GraphPool errors propagate.

        """
        query = """
        MATCH (s:SchemaNode {id: $schema_node_id})
        RETURN s.id AS id,
               s.event_type AS event_type,
               s.pattern AS pattern,
               s.confidence AS confidence
        LIMIT 1
        """
        parameters: dict[str, Any] = {"schema_node_id": schema_node_id}

        records: list[dict[str, Any]] = await self._pool.execute_query(query, parameters)

        if not records:
            raise SchemaNotFoundError(schema_node_id=schema_node_id)

        record = records[0]
        pattern_raw = record.get("pattern")

        # Missing pattern field (None / not stored) → SchemaNotFoundError.
        # Empty string / non-dict JSON / invalid JSON are distinct cases
        # handled below as ValueError (data corruption, Rule 12 fail-loud).
        if pattern_raw is None:
            raise SchemaNotFoundError(schema_node_id=schema_node_id)

        # Parse JSON Schema string → dict. ValueError propagates if invalid
        # JSON or non-dict (null/empty) — Rule 12 fail-loud.
        schema: dict[str, Any] = json.loads(pattern_raw)
        if not isinstance(schema, dict):
            # pattern was valid JSON but not an object (e.g. null, list, number).
            # A JSON Schema must be an object — reject loudly.
            raise ValueError(
                f"SchemaNode.pattern for schema_node_id={schema_node_id!r} "
                f"parsed to {type(schema).__name__}, expected dict"
            )

        # event_type → JSON Schema title (latest-wins: overrides any title
        # embedded in pattern). event_type is the authoritative business
        # key maintained by SchemaExtractorNode.
        event_type = record.get("event_type")
        if event_type:
            schema["title"] = event_type

        log.debug(
            "schema_loaded",
            schema_node_id=schema_node_id,
            event_type=event_type,
            confidence=record.get("confidence"),
        )

        return {
            "schema": schema,
            "schema_node_id": schema_node_id,
        }


__all__ = [
    "SchemaDrivenStructuredOutput",
    "SchemaNotFoundError",
    "StructuredOutputValidationError",
]

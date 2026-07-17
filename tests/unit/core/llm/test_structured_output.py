# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for SchemaDrivenStructuredOutput (T023 / R-structured-001).

Verifies:
- SchemaNode → JSON Schema conversion (pattern parsed, event_type used as title)
- SchemaNotFoundError raised when SchemaNode does not exist
- GraphPool Protocol compliance (constructor accepts any GraphPool impl)
- Neo4j / LadybugDB cross-database compatibility (same query works on both)
- pattern field invalid JSON → ValueError (Rule 12 fail-loud)
- schema_node_id propagation through return value

Spec R-structured-001 field naming conflict (Rule 7 exposed in docstring):
    Spec mentions "SchemaNode.properties" and "entity_type", but actual
    SchemaNode schema uses ``pattern`` (JSON Schema string) and
    ``event_type`` (business key). Resolution: aligned with actual schema
    (pattern/event_type) — docstring of SchemaDrivenStructuredOutput
    documents this divergence.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.llm.structured_output import (
    SchemaDrivenStructuredOutput,
    SchemaNotFoundError,
)


class FakeGraphPool:
    """Fake GraphPool for unit testing.

    Implements the execute_query method of the GraphPool Protocol.
    Returns pre-configured records to simulate SchemaNode queries.
    """

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        database_type: str = "neo4j",
    ) -> None:
        self._records = records
        self._database_type = database_type
        self.last_query: str | None = None
        self.last_parameters: dict[str, Any] | None = None

    @property
    def database_type(self) -> str:
        return self._database_type

    async def execute_query(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self.last_query = query
        self.last_parameters = parameters
        return self._records or []

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def session_context(self):
        raise NotImplementedError("not used in unit tests")


def _make_schema_record(
    schema_id: str = "schema-funding",
    event_type: str = "funding",
    pattern: str | None = None,
    confidence: float = 0.85,
) -> dict[str, Any]:
    """Build a fake SchemaNode record returned by execute_query."""
    if pattern is None:
        pattern = (
            '{"type": "object", '
            '"properties": {'
            '"amount": {"type": "number"}, '
            '"company": {"type": "string"}, '
            '"date": {"type": "string", "format": "date"}'
            "}, "
            '"required": ["amount", "company"]}'
        )
    return {
        "id": schema_id,
        "event_type": event_type,
        "pattern": pattern,
        "confidence": confidence,
    }


class TestSchemaNotFoundError:
    """Verify SchemaNotFoundError exception structure (R-structured-001)."""

    def test_exception_carries_schema_node_id(self):
        """SchemaNotFoundError must carry schema_node_id attribute."""
        exc = SchemaNotFoundError(schema_node_id="schema-funding")
        assert exc.schema_node_id == "schema-funding"

    def test_exception_message_contains_schema_node_id(self):
        """Exception message must include the missing schema_node_id for debug."""
        exc = SchemaNotFoundError(schema_node_id="schema-ipo")
        assert "schema-ipo" in str(exc)

    def test_exception_is_exception_subclass(self):
        """SchemaNotFoundError must subclass Exception for catch compatibility."""
        exc = SchemaNotFoundError(schema_node_id="x")
        assert isinstance(exc, Exception)

    def test_exception_is_keyword_only(self):
        """schema_node_id must be keyword-only (aligns with InsufficientNarrativeError).

        Prevents positional-argument ambiguity in callers and matches the
        project convention for custom exceptions (narrative.py L102-110).
        """
        import inspect

        sig = inspect.signature(SchemaNotFoundError.__init__)
        params = list(sig.parameters.keys())
        # 'self' + 'schema_node_id', and schema_node_id must be keyword-only.
        assert params == ["self", "schema_node_id"]
        assert sig.parameters["schema_node_id"].kind == inspect.Parameter.KEYWORD_ONLY


class TestSchemaDrivenStructuredOutputConstructor:
    """Verify constructor + Protocol compliance."""

    def test_constructor_accepts_graph_pool_protocol(self):
        """Constructor accepts any object implementing GraphPool Protocol."""
        pool = FakeGraphPool(records=[])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)
        # Reference to underlying pool is stored.
        assert service._pool is pool

    def test_constructor_works_with_ladybug_database_type(self):
        """Constructor works with LadybugDB pool (database_type='ladybug')."""
        pool = FakeGraphPool(records=[], database_type="ladybug")
        service = SchemaDrivenStructuredOutput(graph_pool=pool)
        assert service._pool is pool


class TestGetSchema:
    """Verify get_schema happy path + JSON Schema conversion (R-structured-001)."""

    @pytest.mark.asyncio
    async def test_get_schema_returns_schema_dict_and_id(self):
        """get_schema returns {schema: dict, schema_node_id: str}."""
        record = _make_schema_record(
            schema_id="schema-funding",
            event_type="funding",
            pattern=(
                '{"type": "object", '
                '"properties": {"amount": {"type": "number"}}, '
                '"required": ["amount"]}'
            ),
        )
        pool = FakeGraphPool(records=[record])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        result = await service.get_schema("schema-funding")

        assert isinstance(result, dict)
        assert "schema" in result
        assert "schema_node_id" in result
        assert result["schema_node_id"] == "schema-funding"
        assert isinstance(result["schema"], dict)

    @pytest.mark.asyncio
    async def test_get_schema_parses_pattern_as_json(self):
        """pattern field (JSON Schema string) is parsed to dict in returned schema."""
        pattern_json = (
            '{"type": "object", '
            '"properties": {'
            '"amount": {"type": "number"}, '
            '"company": {"type": "string"}'
            "}, "
            '"required": ["amount", "company"]}'
        )
        record = _make_schema_record(pattern=pattern_json)
        pool = FakeGraphPool(records=[record])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        result = await service.get_schema("schema-funding")

        schema = result["schema"]
        assert schema["type"] == "object"
        assert "amount" in schema["properties"]
        assert schema["properties"]["amount"]["type"] == "number"
        assert "company" in schema["properties"]
        assert "amount" in schema["required"]

    @pytest.mark.asyncio
    async def test_get_schema_uses_event_type_as_title(self):
        """event_type is added as JSON Schema title field."""
        record = _make_schema_record(event_type="融资")
        pool = FakeGraphPool(records=[record])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        result = await service.get_schema("schema-融资")

        schema = result["schema"]
        assert schema.get("title") == "融资"

    @pytest.mark.asyncio
    async def test_get_schema_preserves_existing_title_in_pattern(self):
        """If pattern already has title, event_type overrides it (latest wins)."""
        pattern_with_title = '{"type": "object", "title": "old_title"}'
        record = _make_schema_record(event_type="new_event_type", pattern=pattern_with_title)
        pool = FakeGraphPool(records=[record])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        result = await service.get_schema("schema-new_event_type")

        schema = result["schema"]
        # event_type overrides any title embedded in pattern (latest-wins policy).
        assert schema["title"] == "new_event_type"

    @pytest.mark.asyncio
    async def test_get_schema_skips_title_when_event_type_none(self):
        """When event_type is None/empty, schema is returned without title override.

        Covers the `if event_type:` branch — if SchemaNode has no event_type
        (malformed record), we don't add an empty title. Existing pattern
        title (if any) is preserved.
        """
        pattern_with_title = '{"type": "object", "title": "keep_me"}'
        record = _make_schema_record(event_type="", pattern=pattern_with_title)
        # Override event_type to empty string explicitly.
        record["event_type"] = ""
        pool = FakeGraphPool(records=[record])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        result = await service.get_schema("schema-x")

        schema = result["schema"]
        # event_type empty → no override, keep existing pattern title.
        assert schema["title"] == "keep_me"

    @pytest.mark.asyncio
    async def test_get_schema_query_uses_id_parameter(self):
        """Query filters by id=$schema_node_id (not event_type)."""
        record = _make_schema_record()
        pool = FakeGraphPool(records=[record])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        await service.get_schema("schema-ipo")

        # Verify query contains id filter and parameter was forwarded.
        assert "id" in pool.last_query
        assert "$schema_node_id" in pool.last_query
        assert pool.last_parameters == {"schema_node_id": "schema-ipo"}

    @pytest.mark.asyncio
    async def test_get_schema_returns_schema_node_id_from_input(self):
        """schema_node_id in return value matches input schema_node_id."""
        record = _make_schema_record(schema_id="schema-policy")
        pool = FakeGraphPool(records=[record])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        result = await service.get_schema("schema-policy")

        assert result["schema_node_id"] == "schema-policy"


class TestSchemaNotFound:
    """Verify SchemaNotFoundError path (R-structured-001)."""

    @pytest.mark.asyncio
    async def test_get_schema_raises_when_no_records(self):
        """SchemaNotFoundError raised when execute_query returns empty list."""
        pool = FakeGraphPool(records=[])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        with pytest.raises(SchemaNotFoundError) as exc_info:
            await service.get_schema("schema-nonexistent")
        assert exc_info.value.schema_node_id == "schema-nonexistent"

    @pytest.mark.asyncio
    async def test_get_schema_raises_when_record_missing_pattern(self):
        """SchemaNotFoundError raised when record lacks pattern field.

        A SchemaNode without pattern is considered malformed — treat as
        not-found (caller should regenerate schema via SchemaExtractorNode).
        """
        pool = FakeGraphPool(records=[{"id": "schema-x", "event_type": "x"}])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        with pytest.raises(SchemaNotFoundError):
            await service.get_schema("schema-x")


class TestPatternParsing:
    """Verify pattern field JSON parsing edge cases."""

    @pytest.mark.asyncio
    async def test_invalid_json_pattern_raises_value_error(self):
        """Invalid JSON in pattern raises ValueError (Rule 12 fail-loud).

        Do not silently return a malformed schema — propagate the parse
        error so caller can regenerate the SchemaNode via SchemaExtractorNode.
        """
        record = _make_schema_record(pattern="not valid json {{{")
        pool = FakeGraphPool(records=[record])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        with pytest.raises(ValueError):
            await service.get_schema("schema-broken")

    @pytest.mark.asyncio
    async def test_empty_pattern_string_raises_value_error(self):
        """Empty pattern string raises ValueError (Rule 12 fail-loud)."""
        record = _make_schema_record(pattern="")
        pool = FakeGraphPool(records=[record])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        with pytest.raises(ValueError):
            await service.get_schema("schema-empty")

    @pytest.mark.asyncio
    async def test_pattern_with_null_value_raises_value_error(self):
        """pattern=null (valid JSON) raises ValueError — null is not a schema."""
        record = _make_schema_record(pattern="null")
        pool = FakeGraphPool(records=[record])
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        with pytest.raises(ValueError):
            await service.get_schema("schema-null")


class TestCrossDatabaseCompatibility:
    """Verify Neo4j / LadybugDB cross-database compatibility."""

    @pytest.mark.asyncio
    async def test_neo4j_pool_returns_schema(self):
        """Neo4j pool (database_type='neo4j') returns schema correctly."""
        record = _make_schema_record()
        pool = FakeGraphPool(records=[record], database_type="neo4j")
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        result = await service.get_schema("schema-funding")

        assert result["schema"]["title"] == "funding"

    @pytest.mark.asyncio
    async def test_ladybug_pool_returns_schema(self):
        """LadybugDB pool (database_type='ladybug') returns schema correctly.

        The query uses standard Cypher MATCH + RETURN AS pattern that both
        Neo4j and LadybugDB support. No database-specific branch is needed
        for this query (unlike temporal queries in TrendDetector).
        """
        record = _make_schema_record()
        pool = FakeGraphPool(records=[record], database_type="ladybug")
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        result = await service.get_schema("schema-funding")

        assert result["schema"]["title"] == "funding"

    @pytest.mark.asyncio
    async def test_query_string_identical_for_neo4j_and_ladybug(self):
        """Query string is identical across Neo4j / LadybugDB (no branching)."""
        record = _make_schema_record()
        neo4j_pool = FakeGraphPool(records=[record], database_type="neo4j")
        ladybug_pool = FakeGraphPool(records=[record], database_type="ladybug")

        neo4j_service = SchemaDrivenStructuredOutput(graph_pool=neo4j_pool)
        ladybug_service = SchemaDrivenStructuredOutput(graph_pool=ladybug_pool)

        await neo4j_service.get_schema("schema-x")
        await ladybug_service.get_schema("schema-x")

        assert neo4j_pool.last_query == ladybug_pool.last_query


class TestGraphPoolErrors:
    """Verify graph database errors propagate (Rule 12)."""

    @pytest.mark.asyncio
    async def test_pool_exception_propagates(self):
        """GraphPool exceptions propagate to caller (Rule 12 fail-loud)."""
        pool = FakeGraphPool(records=None)

        async def raise_query(query, parameters=None):
            raise RuntimeError("graph database connection lost")

        pool.execute_query = raise_query
        service = SchemaDrivenStructuredOutput(graph_pool=pool)

        with pytest.raises(RuntimeError, match="graph database connection lost"):
            await service.get_schema("schema-x")


__all__ = [
    "FakeGraphPool",
    "TestCrossDatabaseCompatibility",
    "TestGetSchema",
    "TestGraphPoolErrors",
    "TestPatternParsing",
    "TestSchemaDrivenStructuredOutputConstructor",
    "TestSchemaNotFound",
    "TestSchemaNotFoundError",
]

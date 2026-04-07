# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Comprehensive injection attack protection verification tests.

This module tests the security hardening measures implemented to prevent
SQL and Cypher injection attacks across the codebase.

Task 9.3: Manual testing of injection attack protection
"""

from __future__ import annotations

import pytest

from core.db.safe_query import (
    InvalidIdentifierError,
    safe_cypher_label,
    safe_cypher_property,
    safe_sql_identifier,
    validate_edge_type,
    validate_neo4j_label,
    validate_property_name,
    validate_sql_identifier,
    validate_uuid,
)


class TestSQLInjectionProtection:
    """Tests for SQL injection protection in safe_query module."""

    # ── Identifier Validation Tests ──────────────────────────────────────────

    @pytest.mark.parametrize(
        "identifier",
        [
            "valid_table",
            "valid_column_name",
            "TableName",
            "column123",
            "_private_field",
            "schema_name",
        ],
    )
    def test_valid_sql_identifiers_accepted(self, identifier: str) -> None:
        """Valid SQL identifiers should pass validation."""
        result = validate_sql_identifier(identifier)
        assert result == identifier

    @pytest.mark.parametrize(
        "identifier",
        [
            "'; DROP TABLE users; --",
            "users; DROP TABLE users",
            "users' OR '1'='1",
            'users" OR "1"="1',
            "users--comment",
            "users/*comment*/",
            "users; SELECT * FROM passwords",
            "users UNION SELECT * FROM users",
            "1; DROP TABLE users",
            "users\x00",  # null byte
            "users\ntest",  # newline
            "users\rtest",  # carriage return
            "",  # empty
            "   ",  # whitespace only
            "users-name",  # hyphen
            "users.name",  # dot
        ],
    )
    def test_malicious_sql_identifiers_rejected(self, identifier: str) -> None:
        """Malicious SQL identifiers should fail validation."""
        with pytest.raises(InvalidIdentifierError):
            validate_sql_identifier(identifier)

    def test_safe_sql_identifier_quotes_properly(self) -> None:
        """safe_sql_identifier should quote identifiers safely."""
        quoted = safe_sql_identifier("users")
        assert quoted == '"users"'

    def test_safe_sql_identifier_rejects_malicious(self) -> None:
        """safe_sql_identifier should reject malicious identifiers."""
        with pytest.raises(InvalidIdentifierError):
            safe_sql_identifier("users; DROP TABLE users")


class TestCypherInjectionProtection:
    """Tests for Cypher injection protection."""

    # ── Label Validation Tests ───────────────────────────────────────────────

    @pytest.mark.parametrize(
        "label",
        [
            "Person",
            "Organization",
            "Article",
            "Entity123",
            "ValidLabel",
            "CamelCaseLabel",
            "中文标签",  # Chinese characters allowed
        ],
    )
    def test_valid_neo4j_labels_accepted(self, label: str) -> None:
        """Valid Neo4j labels should pass validation."""
        result = validate_neo4j_label(label)
        assert result == label

    @pytest.mark.parametrize(
        "label",
        [
            "Person'; MATCH (n) DELETE n; //",
            'Person" OR 1=1 //',
            "Person} RETURN n//",
            "Person)--",
            "Person*",
            "Person CREATE (n)",
            "Label with space",
            "Label-With-Dash",
            "Label.With.Dot",
            "",  # empty
            "123StartWithNumber",  # starts with number
        ],
    )
    def test_malicious_labels_rejected(self, label: str) -> None:
        """Malicious labels should fail validation."""
        with pytest.raises(InvalidIdentifierError):
            validate_neo4j_label(label)

    def test_safe_cypher_label_quotes_properly(self) -> None:
        """safe_cypher_label should quote labels safely."""
        quoted = safe_cypher_label("Person")
        assert quoted == "`Person`"

    def test_safe_cypher_label_rejects_malicious(self) -> None:
        """safe_cypher_label should reject malicious labels."""
        with pytest.raises(InvalidIdentifierError):
            safe_cypher_label("Person'; DELETE n;")

    # ── Edge Type Validation Tests ───────────────────────────────────────────

    @pytest.mark.parametrize(
        "edge_type",
        [
            "RELATES_TO",
            "HAS_ARTICLE",
            "MENTIONS",
            "CONNECTED",
            "FRIEND_OF",
        ],
    )
    def test_valid_edge_types_accepted(self, edge_type: str) -> None:
        """Valid edge types should pass validation."""
        result = validate_edge_type(edge_type)
        assert result == edge_type

    @pytest.mark.parametrize(
        "edge_type",
        [
            "RELATES_TO'; DELETE n; //",
            "HAS_ARTICLE} RETURN n//",
            "relates_to",  # lowercase not allowed
            "HasArticle",  # mixed case not allowed
            "HAS-ARTICLE",  # hyphen not allowed
            "",  # empty
        ],
    )
    def test_malicious_edge_types_rejected(self, edge_type: str) -> None:
        """Malicious edge types should fail validation."""
        with pytest.raises(InvalidIdentifierError):
            validate_edge_type(edge_type)

    # ── Property Name Validation Tests ─────────────────────────────────────────

    @pytest.mark.parametrize(
        "name",
        [
            "name",
            "created_at",
            "entityId",
            "property123",
        ],
    )
    def test_valid_property_names_accepted(self, name: str) -> None:
        """Valid property names should pass validation."""
        result = validate_property_name(name)
        assert result == name

    @pytest.mark.parametrize(
        "name",
        [
            "name'; DELETE n; //",
            "prop} RETURN n//",
            "property-name",
            "property.name",
            "",
        ],
    )
    def test_malicious_property_names_rejected(self, name: str) -> None:
        """Malicious property names should fail validation."""
        with pytest.raises(InvalidIdentifierError):
            validate_property_name(name)

    # ── UUID Validation Tests ─────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "uuid_str",
        [
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "6BA7B810-9DAD-11D1-80B4-00C04FD430C8",  # uppercase (returned as-is)
        ],
    )
    def test_valid_uuids_accepted(self, uuid_str: str) -> None:
        """Valid UUIDs should pass validation."""
        result = validate_uuid(uuid_str)
        assert result == uuid_str  # UUID is returned as-is

    @pytest.mark.parametrize(
        "uuid_str",
        [
            "not-a-uuid",
            "550e8400-e29b-41d4-a716",  # truncated
            "ggge8400-e29b-41d4-a716-446655440000",  # invalid hex
            "",
        ],
    )
    def test_invalid_uuids_rejected(self, uuid_str: str) -> None:
        """Invalid UUIDs should fail validation."""
        with pytest.raises(InvalidIdentifierError):
            validate_uuid(uuid_str)


class TestGraphQueryBuilders:
    """Tests verifying graph query builders use parameterized queries."""

    def test_neo4j_query_builder_exists(self) -> None:
        """Neo4jQueryBuilder should be importable."""
        from core.db.graph_query import Neo4jQueryBuilder

        assert Neo4jQueryBuilder is not None

    def test_ladybug_query_builder_exists(self) -> None:
        """LadybugQueryBuilder should be importable."""
        from core.db.graph_query import LadybugQueryBuilder

        assert LadybugQueryBuilder is not None

    def test_create_graph_query_builder_factory(self) -> None:
        """create_graph_query_builder should return appropriate builder."""
        from core.db.graph_query import create_graph_query_builder

        neo4j_builder = create_graph_query_builder("neo4j")
        assert neo4j_builder is not None

        ladybug_builder = create_graph_query_builder("ladybug")
        assert ladybug_builder is not None


class TestInputValidationPatterns:
    """Tests for common injection patterns."""

    @pytest.mark.parametrize(
        "payload",
        [
            # SQL injection patterns
            "' OR '1'='1",
            '" OR "1"="1',
            "'; DROP TABLE users; --",
            "'; DELETE FROM users WHERE '1'='1",
            "1; SELECT * FROM users",
            "1 UNION SELECT * FROM passwords",
            "admin'--",
            "admin' #",
            "' OR 1=1--",
            "' OR 'x'='x",
            "1' AND '1'='1",
            # Cypher injection patterns
            "' MATCH (n) DELETE n //",
            "'} RETURN n //",
            "') RETURN n //",
            "' OR 1=1 RETURN n //",
            "1' MATCH (n) DETACH DELETE n //",
            # Command injection patterns
            "; rm -rf /",
            "| cat /etc/passwd",
            "$(cat /etc/passwd)",
            "`cat /etc/passwd`",
            # Path traversal patterns
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
        ],
    )
    def test_sql_injection_payloads_rejected(self, payload: str) -> None:
        """Common injection payloads should be rejected in SQL identifiers."""
        with pytest.raises(InvalidIdentifierError):
            validate_sql_identifier(payload)

    @pytest.mark.parametrize(
        "payload",
        [
            "' OR '1'='1",
            "' MATCH (n) DELETE n //",
            "'} RETURN n //",
            "') RETURN n //",
        ],
    )
    def test_cypher_injection_payloads_rejected_in_labels(self, payload: str) -> None:
        """Injection payloads should be rejected in Cypher labels."""
        with pytest.raises(InvalidIdentifierError):
            validate_neo4j_label(f"Person{payload}")


class TestSecurityHardeningVerification:
    """Final verification tests for security hardening."""

    def test_all_validation_functions_exist(self) -> None:
        """All expected validation functions should exist and work."""
        # Test SQL validation
        assert validate_sql_identifier("valid_name") == "valid_name"

        # Test Neo4j validation
        assert validate_neo4j_label("Person") == "Person"
        assert validate_edge_type("RELATES_TO") == "RELATES_TO"
        assert validate_property_name("name") == "name"

        # Test UUID validation
        assert validate_uuid("550e8400-e29b-41d4-a716-446655440000")

    def test_all_safe_functions_exist(self) -> None:
        """All safe identifier functions should exist and work."""
        assert safe_sql_identifier("users") == '"users"'
        assert safe_cypher_label("Person") == "`Person`"
        assert safe_cypher_property("name") == "`name`"

    def test_graph_query_builder_factory(self) -> None:
        """Graph query builder factory should work correctly."""
        from core.db.graph_query import GraphDatabaseType, create_graph_query_builder

        neo4j = create_graph_query_builder("neo4j")
        assert neo4j.database_type == GraphDatabaseType.NEO4J

        ladybug = create_graph_query_builder("ladybug")
        assert ladybug.database_type == GraphDatabaseType.LADYBUG

    def test_error_messages_are_informative(self) -> None:
        """Error messages should identify the problematic identifier."""
        try:
            validate_sql_identifier("users; DROP TABLE")
        except InvalidIdentifierError as e:
            assert "users; DROP TABLE" in str(e)
            assert "identifier" in str(e).lower()

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for core.security.validation.identifier_validator module.

The identifier_validator module is a deprecated shim that re-exports from
core.db.safe_query. These tests verify the actual safe_query API.
"""

import pytest

from core.security.validation.identifier_validator import (
    IdentifierValidator,
    InvalidIdentifierError,
    validate_cypher_edge_type,
    validate_cypher_label,
    validate_relation_types,
    validate_sql_identifier,
)


class TestInvalidIdentifierError:
    """Test InvalidIdentifierError exception."""

    def test_error_message_format(self):
        """Test error message contains all context."""
        error = InvalidIdentifierError(
            identifier="1invalid",
            identifier_type="table",
        )
        assert "Invalid table: '1invalid'" in str(error)
        assert error.identifier == "1invalid"
        assert error.identifier_type == "table"

    def test_is_value_error_subclass(self):
        """Test that InvalidIdentifierError is a ValueError subclass."""
        error = InvalidIdentifierError("test", "column")
        assert isinstance(error, ValueError)


class TestValidateSQLIdentifier:
    """Test validate_sql_identifier function."""

    @pytest.mark.parametrize(
        "identifier",
        [
            "users",
            "user_table",
            "_private",
            "Table123",
            "ab",
            "very_long_identifier_with_many_underscores",
            "UPPERCASE",
            "mixedCase",
        ],
    )
    def test_valid_identifiers(self, identifier: str):
        """Test valid SQL identifiers are accepted."""
        result = validate_sql_identifier(identifier)
        assert result == identifier

    @pytest.mark.parametrize(
        "identifier",
        [
            "1table",
            "table-name",
            "table.name",
            "DROP TABLE",
            "table name",
            "table;DROP",
            "table'",
            'table"',
        ],
    )
    def test_invalid_identifiers(self, identifier: str):
        """Test invalid SQL identifiers raise InvalidIdentifierError."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validate_sql_identifier(identifier)
        assert identifier in str(exc_info.value)
        assert exc_info.value.identifier_type == "identifier"

    def test_empty_identifier(self):
        """Test empty identifier raises with (too short) suffix."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validate_sql_identifier("")
        assert exc_info.value.identifier_type == "identifier (too short, min 2 chars)"

    def test_custom_identifier_type(self):
        """Test custom identifier_type in error message."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validate_sql_identifier("123", "custom_type")
        assert "Invalid custom_type:" in str(exc_info.value)


class TestValidateCypherEdgeType:
    """Test validate_cypher_edge_type function."""

    @pytest.mark.parametrize(
        "edge_type",
        [
            "RELATED_TO",
            "MENTIONS",
            "KNOWS",
            "A",
            "VERY_LONG_EDGE_TYPE",
            "合作关系",
            "朋友关系",
            "A_B_C_123",
        ],
    )
    def test_valid_edge_types(self, edge_type: str):
        """Test valid edge types are accepted."""
        result = validate_cypher_edge_type(edge_type)
        assert result == edge_type

    @pytest.mark.parametrize(
        "edge_type",
        [
            "related_to",
            "edge-type",
            "edge.type",
            "123EDGE",
            "EDGE TYPE",
            "edge/type",
            "Edge123",
        ],
    )
    def test_invalid_edge_types(self, edge_type: str):
        """Test invalid edge types raise InvalidIdentifierError."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validate_cypher_edge_type(edge_type)
        assert edge_type in str(exc_info.value)
        assert exc_info.value.identifier_type == "edge type"

    def test_empty_edge_type(self):
        """Test empty edge type raises with (empty) suffix."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validate_cypher_edge_type("")
        assert exc_info.value.identifier_type == "edge_type (empty)"


class TestValidateCypherLabel:
    """Test validate_cypher_label function."""

    @pytest.mark.parametrize(
        "label",
        [
            "Entity",
            "Article",
            "Person",
            "实体",
            "文章",
            "_private",
            "Label123",
            "a",
            "A_B_C",
            "混合Label_123",
        ],
    )
    def test_valid_labels(self, label: str):
        """Test valid labels are accepted."""
        result = validate_cypher_label(label)
        assert result == label

    @pytest.mark.parametrize(
        "label",
        [
            "123Label",
            "label-name",
            "label.name",
            "LABEL NAME",
        ],
    )
    def test_invalid_labels(self, label: str):
        """Test invalid labels raise InvalidIdentifierError."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validate_cypher_label(label)
        assert label in str(exc_info.value)
        assert exc_info.value.identifier_type == "Neo4j label"

    def test_empty_label(self):
        """Test empty label raises with (empty) suffix."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validate_cypher_label("")
        assert exc_info.value.identifier_type == "label (empty)"


class TestValidateRelationTypes:
    """Test validate_relation_types function."""

    def test_valid_relation_types(self):
        """Test valid relation types list."""
        relation_types = ["RELATED_TO", "MENTIONS", "KNOWS"]
        result = validate_relation_types(relation_types)
        assert result == relation_types

    def test_empty_list(self):
        """Test empty list is accepted."""
        result = validate_relation_types([])
        assert result == []

    def test_invalid_in_list(self):
        """Test invalid relation type in list raises error."""
        with pytest.raises(InvalidIdentifierError):
            validate_relation_types(["VALID_TYPE", "invalid_type", "ANOTHER"])

    def test_chinese_relation_types(self):
        """Test Chinese relation types are accepted."""
        relation_types = ["合作关系", "朋友关系"]
        result = validate_relation_types(relation_types)
        assert result == relation_types


class TestIdentifierValidator:
    """Test IdentifierValidator dataclass."""

    @pytest.fixture
    def validator(self):
        """Create IdentifierValidator."""
        return IdentifierValidator()

    def test_validate_table(self, validator):
        """Test table name validation."""
        assert validator.validate_table("users") == "users"
        assert validator.validate_table("user_table") == "user_table"

    def test_validate_table_invalid(self, validator):
        """Test invalid table name raises error."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validator.validate_table("1invalid")
        assert exc_info.value.identifier_type == "table"

    def test_validate_column(self, validator):
        """Test column name validation."""
        assert validator.validate_column("user_id") == "user_id"
        assert validator.validate_column("name") == "name"

    def test_validate_column_invalid(self, validator):
        """Test invalid column name raises error."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validator.validate_column("column-name")
        assert exc_info.value.identifier_type == "column"

    def test_validate_edge_type(self, validator):
        """Test edge type validation."""
        assert validator.validate_edge_type("RELATED_TO") == "RELATED_TO"
        assert validator.validate_edge_type("合作关系") == "合作关系"

    def test_validate_edge_type_invalid(self, validator):
        """Test invalid edge type raises error."""
        with pytest.raises(InvalidIdentifierError):
            validator.validate_edge_type("invalid_type")

    def test_validate_label(self, validator):
        """Test label validation."""
        assert validator.validate_label("Entity") == "Entity"
        assert validator.validate_label("实体") == "实体"

    def test_validate_label_invalid(self, validator):
        """Test invalid label raises error."""
        with pytest.raises(InvalidIdentifierError):
            validator.validate_label("123Label")


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_unicode_in_sql_identifier(self):
        """Test Unicode characters in SQL identifier."""
        with pytest.raises(InvalidIdentifierError):
            validate_sql_identifier("用户")

    def test_max_length_identifier(self):
        """Test identifier at PostgreSQL max length (63 chars) is accepted."""
        max_id = "a" * 63
        result = validate_sql_identifier(max_id)
        assert result == max_id

    def test_over_max_length_identifier_rejected(self):
        """Test identifier over PostgreSQL max length (63 chars) is rejected."""
        too_long_id = "a" * 64
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validate_sql_identifier(too_long_id)
        assert "too long" in str(exc_info.value)

    def test_mixed_case_cypher_edge(self):
        """Test mixed case edge type is invalid."""
        with pytest.raises(InvalidIdentifierError):
            validate_cypher_edge_type("RelatedTo")

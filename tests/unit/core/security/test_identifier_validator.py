# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for identifier_validator module."""

import pytest

from core.security.validation.identifier_validator import (
    InvalidIdentifierError,
    IdentifierValidator,
    validate_sql_identifier,
    validate_cypher_edge_type,
    validate_cypher_label,
    validate_relation_types,
)


class TestInvalidIdentifierError:
    """Test InvalidIdentifierError exception."""

    def test_error_message_format(self):
        """Test error message contains all context."""
        error = InvalidIdentifierError(
            identifier="1invalid",
            identifier_type="table",
            pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$",
        )
        assert "Invalid table identifier: '1invalid'" in str(error)
        assert "Must match pattern" in str(error)
        assert error.identifier == "1invalid"
        assert error.identifier_type == "table"
        assert error.pattern == r"^[a-zA-Z_][a-zA-Z0-9_]*$"

    def test_is_value_error_subclass(self):
        """Test that InvalidIdentifierError is a ValueError subclass."""
        error = InvalidIdentifierError("test", "column", "pattern")
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
            "a",
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
            "",
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
        assert exc_info.value.identifier_type == "SQL"

    def test_custom_identifier_type(self):
        """Test custom identifier_type in error message."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validate_sql_identifier("123", "custom_type")
        assert "Invalid custom_type identifier" in str(exc_info.value)


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
            "Edge123",
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
            "related_to",  # lowercase not allowed
            "edge-type",
            "edge.type",
            "123EDGE",
            "",
            "EDGE TYPE",
            "edge/type",
        ],
    )
    def test_invalid_edge_types(self, edge_type: str):
        """Test invalid edge types raise InvalidIdentifierError."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validate_cypher_edge_type(edge_type)
        assert edge_type in str(exc_info.value)
        assert exc_info.value.identifier_type == "edge_type"


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
            "",
            "LABEL NAME",
        ],
    )
    def test_invalid_labels(self, label: str):
        """Test invalid labels raise InvalidIdentifierError."""
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validate_cypher_label(label)
        assert label in str(exc_info.value)
        assert exc_info.value.identifier_type == "label"


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

    def test_validate_table(self):
        """Test table name validation."""
        validator = IdentifierValidator()
        assert validator.validate_table("users") == "users"
        assert validator.validate_table("user_table") == "user_table"

    def test_validate_table_invalid(self):
        """Test invalid table name raises error."""
        validator = IdentifierValidator()
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validator.validate_table("1invalid")
        assert exc_info.value.identifier_type == "table"

    def test_validate_column(self):
        """Test column name validation."""
        validator = IdentifierValidator()
        assert validator.validate_column("user_id") == "user_id"
        assert validator.validate_column("name") == "name"

    def test_validate_column_invalid(self):
        """Test invalid column name raises error."""
        validator = IdentifierValidator()
        with pytest.raises(InvalidIdentifierError) as exc_info:
            validator.validate_column("column-name")
        assert exc_info.value.identifier_type == "column"

    def test_validate_edge_type(self):
        """Test edge type validation."""
        validator = IdentifierValidator()
        assert validator.validate_edge_type("RELATED_TO") == "RELATED_TO"
        assert validator.validate_edge_type("合作关系") == "合作关系"

    def test_validate_edge_type_invalid(self):
        """Test invalid edge type raises error."""
        validator = IdentifierValidator()
        with pytest.raises(InvalidIdentifierError):
            validator.validate_edge_type("invalid_type")

    def test_validate_label(self):
        """Test label validation."""
        validator = IdentifierValidator()
        assert validator.validate_label("Entity") == "Entity"
        assert validator.validate_label("实体") == "实体"

    def test_validate_label_invalid(self):
        """Test invalid label raises error."""
        validator = IdentifierValidator()
        with pytest.raises(InvalidIdentifierError):
            validator.validate_label("123Label")

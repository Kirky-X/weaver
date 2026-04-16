# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for core.security.validation.identifier_validator module."""

import pytest

from core.security.validation.identifier_validator import (
    IdentifierValidator,
    InvalidIdentifierError,
    validate_cypher_edge_type,
    validate_cypher_label,
    validate_relation_types,
    validate_sql_identifier,
)


class TestValidateSqlIdentifier:
    """Test validate_sql_identifier function."""

    def test_valid_identifier(self):
        """Test valid SQL identifier."""
        result = validate_sql_identifier("users")

        assert result == "users"

    def test_valid_identifier_with_underscore(self):
        """Test valid identifier with underscore."""
        result = validate_sql_identifier("user_table")

        assert result == "user_table"

    def test_valid_identifier_starting_with_underscore(self):
        """Test valid identifier starting with underscore."""
        result = validate_sql_identifier("_private")

        assert result == "_private"

    def test_valid_identifier_with_numbers(self):
        """Test valid identifier with numbers."""
        result = validate_sql_identifier("table1")

        assert result == "table1"

    def test_invalid_identifier_starts_with_number(self):
        """Test invalid identifier starting with number."""
        with pytest.raises(InvalidIdentifierError):
            validate_sql_identifier("1table")

    def test_invalid_identifier_with_special_chars(self):
        """Test invalid identifier with special characters."""
        with pytest.raises(InvalidIdentifierError):
            validate_sql_identifier("user-table")

    def test_invalid_identifier_with_space(self):
        """Test invalid identifier with space."""
        with pytest.raises(InvalidIdentifierError):
            validate_sql_identifier("user table")


class TestValidateCypherEdgeType:
    """Test validate_cypher_edge_type function."""

    def test_valid_edge_type(self):
        """Test valid Cypher edge type."""
        result = validate_cypher_edge_type("RELATED_TO")

        assert result == "RELATED_TO"

    def test_valid_edge_type_simple(self):
        """Test simple valid edge type."""
        result = validate_cypher_edge_type("MENTIONS")

        assert result == "MENTIONS"

    def test_valid_edge_type_with_chinese(self):
        """Test edge type with Chinese characters."""
        result = validate_cypher_edge_type("合作关系")

        assert result == "合作关系"

    def test_invalid_edge_type_lowercase(self):
        """Test invalid edge type with lowercase."""
        with pytest.raises(InvalidIdentifierError):
            validate_cypher_edge_type("related_to")

    def test_invalid_edge_type_with_special_chars(self):
        """Test invalid edge type with special characters."""
        with pytest.raises(InvalidIdentifierError):
            validate_cypher_edge_type("RELATED-TO")


class TestValidateCypherLabel:
    """Test validate_cypher_label function."""

    def test_valid_label(self):
        """Test valid Cypher label."""
        result = validate_cypher_label("Entity")

        assert result == "Entity"

    def test_valid_label_with_chinese(self):
        """Test label with Chinese characters."""
        result = validate_cypher_label("实体")

        assert result == "实体"

    def test_valid_label_with_underscore(self):
        """Test valid label with underscore."""
        result = validate_cypher_label("User_Entity")

        assert result == "User_Entity"

    def test_invalid_label_starts_with_number(self):
        """Test invalid label starting with number."""
        with pytest.raises(InvalidIdentifierError):
            validate_cypher_label("1Entity")


class TestValidateRelationTypes:
    """Test validate_relation_types function."""

    def test_valid_relation_types(self):
        """Test valid relation types list."""
        result = validate_relation_types(["RELATED_TO", "MENTIONS"])

        assert result == ["RELATED_TO", "MENTIONS"]

    def test_empty_list(self):
        """Test empty list is valid."""
        result = validate_relation_types([])

        assert result == []

    def test_invalid_relation_type(self):
        """Test invalid relation type raises error."""
        with pytest.raises(InvalidIdentifierError):
            validate_relation_types(["related_to"])


class TestInvalidIdentifierError:
    """Test InvalidIdentifierError exception."""

    def test_error_message(self):
        """Test error message format."""
        try:
            validate_sql_identifier("1invalid")
        except InvalidIdentifierError as e:
            assert "1invalid" in str(e)
            assert "SQL" in str(e)

    def test_error_attributes(self):
        """Test error attributes."""
        error = InvalidIdentifierError(
            identifier="bad-id",
            identifier_type="test",
            pattern="test-pattern",
        )

        assert error.identifier == "bad-id"
        assert error.identifier_type == "test"
        assert error.pattern == "test-pattern"


class TestIdentifierValidator:
    """Test IdentifierValidator class."""

    @pytest.fixture
    def validator(self):
        """Create IdentifierValidator."""
        return IdentifierValidator()

    def test_validate_table(self, validator):
        """Test validate_table method."""
        result = validator.validate_table("users")

        assert result == "users"

    def test_validate_column(self, validator):
        """Test validate_column method."""
        result = validator.validate_column("id")

        assert result == "id"

    def test_validate_edge_type(self, validator):
        """Test validate_edge_type method."""
        result = validator.validate_edge_type("RELATED_TO")

        assert result == "RELATED_TO"

    def test_validate_label(self, validator):
        """Test validate_label method."""
        result = validator.validate_label("Entity")

        assert result == "Entity"

    def test_validate_table_invalid(self, validator):
        """Test validate_table raises on invalid."""
        with pytest.raises(InvalidIdentifierError):
            validator.validate_table("1invalid")


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string_identifier(self):
        """Test empty string is invalid."""
        with pytest.raises(InvalidIdentifierError):
            validate_sql_identifier("")

    def test_unicode_in_sql_identifier(self):
        """Test Unicode characters in SQL identifier."""
        # Standard SQL identifiers should not allow Chinese
        with pytest.raises(InvalidIdentifierError):
            validate_sql_identifier("用户")

    def test_max_length_identifier(self):
        """Test very long identifier."""
        long_id = "a" * 100
        result = validate_sql_identifier(long_id)

        assert result == long_id

    def test_mixed_case_cypher_edge(self):
        """Test mixed case edge type is invalid."""
        with pytest.raises(InvalidIdentifierError):
            validate_cypher_edge_type("RelatedTo")

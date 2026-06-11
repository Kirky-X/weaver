# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SQL identifier validation in query builders.

This module tests the validate_sql_identifier() function added for SQL injection
protection in the migration module. The function enforces:
- Minimum 2 characters (prevent single-char identifiers)
- Maximum 63 characters (PostgreSQL identifier limit)
- Only alphanumeric and underscore characters
- Must start with letter or underscore

Tests cover:
- Valid identifiers acceptance
- Length validation (too short, too long)
- Character validation (special chars, SQL injection patterns)
- Error message quality
"""

from __future__ import annotations

import pytest

from core.db.query_builders import validate_sql_identifier


class TestValidateSQLIdentifier:
    """Tests for validate_sql_identifier function."""

    # ── Valid Identifier Tests ───────────────────────────────────────────────

    @pytest.mark.parametrize(
        "identifier",
        [
            "users",
            "article_table",
            "_temp",
            "valid_table",
            "valid_column_name",
            "TableName",
            "column123",
            "_private_field",
            "schema_name",
            "ab",  # minimum length (2 chars)
            "a" * 63,  # maximum length (63 chars)
            "test_table_123",
            "UserProfiles",
        ],
    )
    def test_valid_identifiers_pass_validation(self, identifier: str) -> None:
        """Valid SQL identifiers should pass validation and return unchanged."""
        result = validate_sql_identifier(identifier)
        assert result == identifier

    # ── Length Validation Tests ──────────────────────────────────────────────

    def test_reject_single_character_identifier(self) -> None:
        """Single character identifiers should be rejected (too short)."""
        with pytest.raises(ValueError) as exc_info:
            validate_sql_identifier("a")
        assert "too short" in str(exc_info.value).lower()
        assert "a" in str(exc_info.value)

    def test_reject_single_underscore_identifier(self) -> None:
        """Single underscore should be rejected (too short)."""
        with pytest.raises(ValueError) as exc_info:
            validate_sql_identifier("_")
        assert "too short" in str(exc_info.value).lower()

    def test_reject_empty_string(self) -> None:
        """Empty string should be rejected."""
        with pytest.raises(ValueError) as exc_info:
            validate_sql_identifier("")
        assert "too short" in str(exc_info.value).lower()

    def test_reject_over_63_characters(self) -> None:
        """Identifiers longer than 63 characters should be rejected."""
        long_identifier = "a" * 64
        with pytest.raises(ValueError) as exc_info:
            validate_sql_identifier(long_identifier)
        assert "Invalid SQL identifier" in str(exc_info.value)

    def test_accept_exactly_63_characters(self) -> None:
        """Identifier with exactly 63 characters should be accepted."""
        max_length_identifier = "a" * 63
        result = validate_sql_identifier(max_length_identifier)
        assert result == max_length_identifier

    def test_accept_exactly_2_characters(self) -> None:
        """Identifier with exactly 2 characters should be accepted."""
        min_length_identifier = "ab"
        result = validate_sql_identifier(min_length_identifier)
        assert result == min_length_identifier

    # ── SQL Injection Pattern Tests ──────────────────────────────────────────

    @pytest.mark.parametrize(
        "identifier",
        [
            "users; DROP TABLE",
            "users' OR '1'='1",
            'users" OR "1"="1',
            "users--comment",
            "users/*comment*/",
            "users; SELECT * FROM passwords",
            "users UNION SELECT * FROM users",
            "1; DROP TABLE users",
            "'; DROP TABLE users; --",
            "' OR '1'='1",
            "admin'--",
            "admin' #",
            "' OR 1=1--",
        ],
    )
    def test_reject_sql_injection_patterns(self, identifier: str) -> None:
        """SQL injection patterns should be rejected."""
        with pytest.raises(ValueError) as exc_info:
            validate_sql_identifier(identifier)
        assert "Invalid SQL identifier" in str(exc_info.value)
        # Verify the malicious identifier is mentioned in error message
        assert identifier in str(exc_info.value) or identifier[:20] in str(exc_info.value)

    # ── Special Character Tests ──────────────────────────────────────────────

    @pytest.mark.parametrize(
        "identifier",
        [
            "table name",  # space
            "table/name",  # forward slash
            "table.name",  # dot
            "table-name",  # hyphen
            "table@name",  # at symbol
            "table#name",  # hash
            "table$name",  # dollar sign
            "table%name",  # percent
            "table&name",  # ampersand
            "table*name",  # asterisk
            "table+name",  # plus
            "table=name",  # equals
            "table?name",  # question mark
            "table!name",  # exclamation
            "table~name",  # tilde
            "table`name",  # backtick
            "table^name",  # caret
            "table|name",  # pipe
            "table\\name",  # backslash
        ],
    )
    def test_reject_special_characters(self, identifier: str) -> None:
        """Identifiers with special characters should be rejected."""
        with pytest.raises(ValueError) as exc_info:
            validate_sql_identifier(identifier)
        assert "Invalid SQL identifier" in str(exc_info.value)

    @pytest.mark.parametrize(
        "identifier",
        [
            "users\x00",  # null byte
            "users\ntest",  # newline
            "users\rtest",  # carriage return
            "users\ttest",  # tab
            "   ",  # whitespace only
            " table",  # leading space
            "table ",  # trailing space
        ],
    )
    def test_reject_whitespace_and_control_characters(self, identifier: str) -> None:
        """Identifiers with whitespace or control characters should be rejected."""
        with pytest.raises(ValueError) as exc_info:
            validate_sql_identifier(identifier)
        assert "Invalid SQL identifier" in str(exc_info.value)

    # ── Error Message Quality Tests ──────────────────────────────────────────

    def test_error_message_contains_identifier_for_short(self) -> None:
        """Error message should contain the identifier when too short."""
        test_identifier = "x"
        with pytest.raises(ValueError) as exc_info:
            validate_sql_identifier(test_identifier)
        error_message = str(exc_info.value)
        assert test_identifier in error_message
        assert "too short" in error_message.lower()

    def test_error_message_contains_identifier_for_invalid(self) -> None:
        """Error message should contain the identifier when invalid."""
        test_identifier = "table-name"
        with pytest.raises(ValueError) as exc_info:
            validate_sql_identifier(test_identifier)
        error_message = str(exc_info.value)
        assert test_identifier in error_message or "table" in error_message

    def test_error_message_includes_malicious_payload(self) -> None:
        """Error message should include the malicious payload for debugging."""
        malicious = "users; DROP TABLE users"
        with pytest.raises(ValueError) as exc_info:
            validate_sql_identifier(malicious)
        error_message = str(exc_info.value)
        # The error should reference the malicious input
        assert "users" in error_message

    # ── Edge Case Tests ──────────────────────────────────────────────────────

    def test_identifier_starting_with_underscore(self) -> None:
        """Identifiers starting with underscore should be valid."""
        result = validate_sql_identifier("_test_table")
        assert result == "_test_table"

    def test_identifier_with_mixed_case(self) -> None:
        """Identifiers with mixed case should be valid."""
        result = validate_sql_identifier("UserTable_Name")
        assert result == "UserTable_Name"

    def test_identifier_with_numbers_not_at_start(self) -> None:
        """Identifiers with numbers (not at start) should be valid."""
        result = validate_sql_identifier("table123")
        assert result == "table123"

    def test_identifier_cannot_start_with_number(self) -> None:
        """Identifiers starting with numbers should be rejected."""
        with pytest.raises(ValueError):
            validate_sql_identifier("123table")

    def test_none_raises_type_error(self) -> None:
        """None should raise TypeError (not ValueError)."""
        with pytest.raises((TypeError, ValueError)):
            validate_sql_identifier(None)  # type: ignore[arg-type]


class TestValidateSQLIdentifierIntegration:
    """Integration tests for validate_sql_identifier in real usage scenarios."""

    def test_migration_table_name_validation(self) -> None:
        """Test typical migration table names pass validation."""
        migration_tables = [
            "articles",
            "source_authorities",
            "llm_failures",
            "llm_usage",
            "source_configs",
            "entities",
            "relationships",
        ]
        for table in migration_tables:
            assert validate_sql_identifier(table) == table

    def test_migration_column_name_validation(self) -> None:
        """Test typical migration column names pass validation."""
        migration_columns = [
            "id",
            "source_url",
            "source_host",
            "created_at",
            "updated_at",
            "credibility_score",
            "persist_status",
        ]
        for column in migration_columns:
            assert validate_sql_identifier(column) == column

    def test_malicious_migration_inputs_rejected(self) -> None:
        """Test that malicious inputs in migration context are rejected."""
        malicious_inputs = [
            "articles; DROP TABLE articles; --",
            "articles' OR '1'='1",
            "column; DELETE FROM users",
            "table`name`",
        ]
        for malicious in malicious_inputs:
            with pytest.raises(ValueError):
                validate_sql_identifier(malicious)

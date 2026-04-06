# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for migration exceptions."""

import pytest

from modules.migration.exceptions import (
    BatchFailedError,
    ConnectionError,
    IntegrityError,
    MigrationError,
    SchemaMismatchError,
    TypeConversionError,
    UnsupportedDatabaseError,
    ValidationFailedError,
)


class TestMigrationError:
    """Tests for MigrationError base class."""

    def test_basic_error(self):
        """Test basic error creation."""
        error = MigrationError("Something went wrong")
        assert str(error) == "Something went wrong"

    def test_error_with_table(self):
        """Test error with table name."""
        error = MigrationError("Error occurred", table="articles")
        assert "Error occurred" in str(error)
        assert "table: articles" in str(error)

    def test_error_with_cause(self):
        """Test error with cause exception."""
        original = ValueError("Original error")
        error = MigrationError("Wrapped error", cause=original)
        assert "Wrapped error" in str(error)
        assert "caused by: Original error" in str(error)

    def test_error_with_table_and_cause(self):
        """Test error with both table and cause."""
        original = RuntimeError("DB crashed")
        error = MigrationError("Migration failed", table="users", cause=original)
        error_str = str(error)
        assert "Migration failed" in error_str
        assert "table: users" in error_str
        assert "caused by: DB crashed" in error_str


class TestSchemaMismatchError:
    """Tests for SchemaMismatchError."""

    def test_schema_mismatch(self):
        """Test schema mismatch error message."""
        error = SchemaMismatchError(
            source_table="old_articles",
            target_table="new_articles",
            details="column types differ",
        )
        assert "Schema mismatch" in str(error)
        assert "old_articles" in str(error)
        assert "new_articles" in str(error)
        assert "column types differ" in str(error)


class TestTypeConversionError:
    """Tests for TypeConversionError."""

    def test_type_conversion_error(self):
        """Test type conversion error message."""
        error = TypeConversionError(
            column="created_at",
            value="invalid_date",
            source_type="varchar",
            target_type="timestamp",
        )
        assert "Cannot convert" in str(error)
        assert "created_at" in str(error)
        assert "varchar" in str(error)
        assert "timestamp" in str(error)

    def test_type_conversion_error_with_table(self):
        """Test type conversion error with table."""
        error = TypeConversionError(
            column="id",
            value="abc",
            source_type="text",
            target_type="integer",
            table="articles",
        )
        assert "table: articles" in str(error)


class TestConnectionError:
    """Tests for ConnectionError."""

    def test_connection_error(self):
        """Test connection error message."""
        error = ConnectionError(
            database="postgres",
            operation="INSERT",
        )
        assert "Connection failed" in str(error)
        assert "postgres" in str(error)
        assert "INSERT" in str(error)

    def test_connection_error_with_cause(self):
        """Test connection error with cause."""
        original = OSError("Network unreachable")
        error = ConnectionError(
            database="neo4j",
            operation="QUERY",
            cause=original,
        )
        assert "caused by: Network unreachable" in str(error)


class TestIntegrityError:
    """Tests for IntegrityError."""

    def test_integrity_error(self):
        """Test integrity error message."""
        error = IntegrityError(
            table="users",
            constraint="email_unique",
            details="duplicate key value",
        )
        assert "Integrity constraint violation" in str(error)
        assert "users.email_unique" in str(error)
        assert "duplicate key value" in str(error)


class TestBatchFailedError:
    """Tests for BatchFailedError."""

    def test_batch_failed_error(self):
        """Test batch failed error message."""
        error = BatchFailedError(
            table="articles",
            batch_offset=1000,
            succeeded=50,
            failed=10,
        )
        assert "Batch failed" in str(error)
        assert "articles" in str(error)
        assert "offset 1000" in str(error)
        assert "50 succeeded" in str(error)
        assert "10 failed" in str(error)

    def test_batch_failed_error_with_cause(self):
        """Test batch failed error with cause."""
        original = Exception("Out of memory")
        error = BatchFailedError(
            table="posts",
            batch_offset=500,
            succeeded=25,
            failed=5,
            cause=original,
        )
        assert "caused by: Out of memory" in str(error)


class TestValidationFailedError:
    """Tests for ValidationFailedError."""

    def test_validation_failed_error(self):
        """Test validation failed error message."""
        error = ValidationFailedError(
            table="articles",
            expected=1000,
            actual=995,
        )
        assert "Validation failed" in str(error)
        assert "articles" in str(error)
        assert "expected 1000" in str(error)
        assert "got 995" in str(error)


class TestUnsupportedDatabaseError:
    """Tests for UnsupportedDatabaseError."""

    def test_unsupported_database_error(self):
        """Test unsupported database error message."""
        error = UnsupportedDatabaseError(
            database="mysql",
            supported=["postgres", "neo4j"],
        )
        assert "Unsupported database" in str(error)
        assert "mysql" in str(error)
        assert "postgres" in str(error)
        assert "neo4j" in str(error)

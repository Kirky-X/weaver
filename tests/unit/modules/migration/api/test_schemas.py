"""Tests for migration API schemas validation."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from modules.migration.api.schemas import (
    ErrorResponse,
    ItemProgress,
    MappingInfo,
    MappingListResponse,
    MappingUploadRequest,
    MigrationCancelResponse,
    MigrationProgressResponse,
    MigrationRequest,
    MigrationStatusResponse,
)


class TestMigrationRequestSchema:
    """Test MigrationRequest schema validation."""

    @pytest.mark.parametrize(
        "source_db,target_db",
        [
            ("postgres", "duckdb"),
            ("duckdb", "postgres"),
            ("neo4j", "ladybug"),
            ("ladybug", "neo4j"),
            ("postgres", "postgres"),
            ("neo4j", "neo4j"),
        ],
    )
    def test_should_accept_valid_database_combinations(self, source_db: str, target_db: str):
        """Test valid database type combinations."""
        request = MigrationRequest(source_db=source_db, target_db=target_db)
        assert request.source_db == source_db
        assert request.target_db == target_db

    @pytest.mark.parametrize(
        "batch_size,valid",
        [
            (100, True),
            (5000, True),
            (50000, True),
            (99, False),
            (50001, False),
            (0, False),
            (-1, False),
        ],
    )
    def test_should_validate_batch_size_bounds(self, batch_size: int, valid: bool):
        """Test batch size validation (ge=100, le=50000)."""
        if valid:
            request = MigrationRequest(
                source_db="postgres",
                target_db="duckdb",
                batch_size=batch_size,
            )
            assert request.batch_size == batch_size
        else:
            with pytest.raises(ValidationError):
                MigrationRequest(
                    source_db="postgres",
                    target_db="duckdb",
                    batch_size=batch_size,
                )

    def test_should_use_default_batch_size(self):
        """Test that batch_size defaults to 5000."""
        request = MigrationRequest(source_db="postgres", target_db="duckdb")
        assert request.batch_size == 5000

    def test_should_use_default_strict_mode(self):
        """Test that strict_mode defaults to False."""
        request = MigrationRequest(source_db="postgres", target_db="duckdb")
        assert request.strict_mode is False

    @pytest.mark.parametrize("strict_mode", [True, False])
    def test_should_accept_strict_mode_flag(self, strict_mode: bool):
        """Test strict_mode flag acceptance."""
        request = MigrationRequest(
            source_db="postgres",
            target_db="duckdb",
            strict_mode=strict_mode,
        )
        assert request.strict_mode == strict_mode

    def test_should_accept_optional_tables_field(self):
        """Test optional tables field."""
        tables = ["users", "orders", "products"]
        request = MigrationRequest(
            source_db="postgres",
            target_db="duckdb",
            tables=tables,
        )
        assert request.tables == tables

    def test_should_accept_null_tables_field(self):
        """Test that tables field can be None."""
        request = MigrationRequest(
            source_db="postgres",
            target_db="duckdb",
            tables=None,
        )
        assert request.tables is None

    def test_should_accept_optional_incremental_key(self):
        """Test optional incremental_key field."""
        request = MigrationRequest(
            source_db="postgres",
            target_db="duckdb",
            incremental_key="updated_at",
        )
        assert request.incremental_key == "updated_at"

    def test_should_accept_optional_incremental_since(self):
        """Test optional incremental_since field."""
        since_value = "2024-01-01T00:00:00Z"
        request = MigrationRequest(
            source_db="postgres",
            target_db="duckdb",
            incremental_since=since_value,
        )
        assert request.incremental_since == since_value

    def test_should_accept_optional_mapping_file(self):
        """Test optional mapping_file field."""
        request = MigrationRequest(
            source_db="neo4j",
            target_db="ladybug",
            mapping_file="/path/to/mapping.yaml",
        )
        assert request.mapping_file == "/path/to/mapping.yaml"

    def test_should_accept_all_optional_fields_together(self):
        """Test that all optional fields can be provided together."""
        request = MigrationRequest(
            source_db="postgres",
            target_db="duckdb",
            tables=["table1"],
            batch_size=1000,
            incremental_key="id",
            incremental_since=100,
            mapping_file="/mapping.yaml",
            strict_mode=True,
        )
        assert request.tables == ["table1"]
        assert request.batch_size == 1000
        assert request.incremental_key == "id"
        assert request.incremental_since == 100
        assert request.mapping_file == "/mapping.yaml"
        assert request.strict_mode is True

    def test_should_require_source_db(self):
        """Test that source_db is required."""
        with pytest.raises(ValidationError):
            MigrationRequest(target_db="duckdb")

    def test_should_require_target_db(self):
        """Test that target_db is required."""
        with pytest.raises(ValidationError):
            MigrationRequest(source_db="postgres")


class TestMigrationStatusResponseSchema:
    """Test MigrationStatusResponse schema validation."""

    def test_should_create_status_response(self):
        """Test creating a migration status response."""
        response = MigrationStatusResponse(
            task_id="task-123",
            status="started",
            message="Migration started successfully",
        )
        assert response.task_id == "task-123"
        assert response.status == "started"
        assert response.message == "Migration started successfully"

    def test_should_validate_required_fields(self):
        """Test that all fields are required."""
        with pytest.raises(ValidationError):
            MigrationStatusResponse(task_id="task-123")


class TestMigrationProgressResponseSchema:
    """Test MigrationProgressResponse schema validation."""

    def test_should_create_progress_response(self):
        """Test creating a migration progress response."""
        started_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        response = MigrationProgressResponse(
            task_id="task-456",
            source_db="postgres",
            target_db="duckdb",
            items=[],
            total_migrated=0,
            total_expected=1000,
            started_at=started_at,
            elapsed_seconds=0.0,
            status="running",
        )
        assert response.task_id == "task-456"
        assert response.source_db == "postgres"
        assert response.target_db == "duckdb"
        assert response.items == []
        assert response.total_migrated == 0
        assert response.total_expected == 1000
        assert response.started_at == started_at
        assert response.elapsed_seconds == 0.0
        assert response.status == "running"
        assert response.error is None

    def test_should_accept_optional_error_field(self):
        """Test that error field is optional."""
        started_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        response = MigrationProgressResponse(
            task_id="task-789",
            source_db="neo4j",
            target_db="ladybug",
            items=[],
            total_migrated=500,
            total_expected=1000,
            started_at=started_at,
            elapsed_seconds=120.5,
            status="failed",
            error="Connection timeout",
        )
        assert response.error == "Connection timeout"


class TestItemProgressSchema:
    """Test ItemProgress schema validation."""

    def test_should_create_item_progress(self):
        """Test creating an item progress entry."""
        item = ItemProgress(
            table="users",
            total=1000,
            migrated=500,
            percent=50.0,
            status="running",
        )
        assert item.table == "users"
        assert item.total == 1000
        assert item.migrated == 500
        assert item.percent == 50.0
        assert item.status == "running"
        assert item.error is None

    def test_should_accept_optional_error_field(self):
        """Test that error field is optional."""
        item = ItemProgress(
            table="orders",
            total=2000,
            migrated=1500,
            percent=75.0,
            status="error",
            error="Type conversion failed",
        )
        assert item.error == "Type conversion failed"

    def test_should_validate_percentage_calculation(self):
        """Test that percent field accepts calculated values."""
        item = ItemProgress(
            table="products",
            total=100,
            migrated=33,
            percent=33.0,
            status="running",
        )
        # Verify the percent matches the expected calculation
        expected_percent = (item.migrated / item.total) * 100
        assert abs(item.percent - expected_percent) < 0.01


class TestErrorResponseSchema:
    """Test ErrorResponse schema validation."""

    def test_should_create_error_response(self):
        """Test creating an error response."""
        response = ErrorResponse(
            error="ValidationError",
            detail="batch_size must be between 100 and 50000",
        )
        assert response.error == "ValidationError"
        assert response.detail == "batch_size must be between 100 and 50000"

    def test_should_accept_null_detail(self):
        """Test that detail field can be None."""
        response = ErrorResponse(error="InternalServerError")
        assert response.error == "InternalServerError"
        assert response.detail is None


class TestOtherResponseSchemas:
    """Test other response schemas validation."""

    def test_should_create_mapping_info(self):
        """Test creating MappingInfo schema."""
        mapping = MappingInfo(
            name="user_mapping",
            node_mappings=["User", "Profile"],
            rel_mappings=["HAS_PROFILE"],
        )
        assert mapping.name == "user_mapping"
        assert mapping.node_mappings == ["User", "Profile"]
        assert mapping.rel_mappings == ["HAS_PROFILE"]

    def test_should_create_mapping_list_response(self):
        """Test creating MappingListResponse schema."""
        mappings = [
            MappingInfo(
                name="mapping1",
                node_mappings=["Node1"],
                rel_mappings=["REL1"],
            ),
            MappingInfo(
                name="mapping2",
                node_mappings=["Node2"],
                rel_mappings=["REL2"],
            ),
        ]
        response = MappingListResponse(mappings=mappings)
        assert len(response.mappings) == 2
        assert response.mappings[0].name == "mapping1"
        assert response.mappings[1].name == "mapping2"

    def test_should_create_migration_cancel_response(self):
        """Test creating MigrationCancelResponse schema."""
        response = MigrationCancelResponse(
            task_id="task-999",
            status="cancelled",
            message="Migration cancelled by user",
        )
        assert response.task_id == "task-999"
        assert response.status == "cancelled"
        assert response.message == "Migration cancelled by user"

    def test_should_create_mapping_upload_request(self):
        """Test creating MappingUploadRequest schema."""
        yaml_content = """
        nodes:
          - source: User
            target: Person
        """
        request = MappingUploadRequest(
            name="user_person_mapping",
            content=yaml_content,
        )
        assert request.name == "user_person_mapping"
        assert request.content == yaml_content

    def test_should_require_mapping_upload_fields(self):
        """Test that MappingUploadRequest requires all fields."""
        with pytest.raises(ValidationError):
            MappingUploadRequest(name="test")
        with pytest.raises(ValidationError):
            MappingUploadRequest(content="content")

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for migration API routes."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.migration.api.routes import router
from tests.helpers import (
    create_migration_request_data,
)


@pytest.fixture
def app():
    """Create FastAPI app with migration router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app, mock_migration_service):
    """Create test client with mocked migration service."""
    # Override the dependency
    from modules.migration.api.dependencies import get_migration_service

    app.dependency_overrides[get_migration_service] = lambda: mock_migration_service

    # Use raise_server_exceptions=False to avoid background task errors
    # affecting the test results
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_migration_service():
    """Create mock migration service."""
    service = Mock()
    service.create_task = Mock(return_value="task_123")
    service.run_migration = AsyncMock()
    service.get_status = Mock(
        return_value={
            "status": "pending",
            "config": Mock(source_db="postgres", target_db="duckdb"),
            "created_at": datetime.now(),
            "started_at": None,
            "progress": {},
            "result": None,
        }
    )
    service.cancel_task = Mock(return_value=True)
    return service


# ============================================================================
# Test Relational Migration Endpoint (POST /migration/relational)
# ============================================================================


class TestRelationalMigrationEndpoint:
    """Test POST /migration/relational endpoint."""

    @pytest.mark.parametrize(
        "source_db,target_db",
        [
            ("postgres", "duckdb"),
            ("duckdb", "postgres"),
            ("POSTGRES", "DUCKDB"),  # Case insensitive
            ("Postgres", "DuckDB"),  # Mixed case
        ],
    )
    def test_should_start_relational_migration(
        self, client, mock_migration_service, source_db, target_db
    ):
        """Test starting relational migration with valid database pairs."""
        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.post(
                "/migration/relational",
                json=create_migration_request_data(
                    source_db=source_db,
                    target_db=target_db,
                    batch_size=5000,
                ),
            )

            assert response.status_code == 200
            data = response.json()
            assert data["task_id"] == "task_123"
            assert data["status"] == "pending"
            assert "started" in data["message"].lower()

    def test_should_start_relational_migration_with_all_optional_params(
        self, client, mock_migration_service
    ):
        """Test starting migration with all optional parameters."""
        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.post(
                "/migration/relational",
                json={
                    "source_db": "postgres",
                    "target_db": "duckdb",
                    "tables": ["users", "orders"],
                    "batch_size": 10000,
                    "incremental_key": "updated_at",
                    "incremental_since": "2024-01-01T00:00:00",
                    "mapping_file": "/path/to/mapping.yaml",
                    "strict_mode": True,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["task_id"] == "task_123"

    def test_should_start_relational_migration_with_default_values(
        self, client, mock_migration_service
    ):
        """Test starting migration with only required fields."""
        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.post(
                "/migration/relational",
                json={
                    "source_db": "postgres",
                    "target_db": "duckdb",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["task_id"] == "task_123"

    @pytest.mark.parametrize("batch_size", [100, 5000, 25000, 50000])
    def test_should_accept_valid_batch_sizes(self, client, mock_migration_service, batch_size):
        """Test accepting batch sizes within valid range."""
        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.post(
                "/migration/relational",
                json=create_migration_request_data(
                    source_db="postgres",
                    target_db="duckdb",
                    batch_size=batch_size,
                ),
            )

            assert response.status_code == 200

    @pytest.mark.parametrize(
        "source_db",
        [
            "mysql",
            "oracle",
            "sqlserver",
            "sqlite",
            "mongodb",
            "",
        ],
    )
    def test_should_reject_invalid_source_db(self, client, source_db):
        """Test rejecting invalid source database types."""
        response = client.post(
            "/migration/relational",
            json=create_migration_request_data(
                source_db=source_db,
                target_db="duckdb",
            ),
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid source_db" in data["detail"]

    @pytest.mark.parametrize(
        "target_db",
        [
            "mysql",
            "oracle",
            "sqlserver",
            "sqlite",
            "mongodb",
            "",
        ],
    )
    def test_should_reject_invalid_target_db(self, client, target_db):
        """Test rejecting invalid target database types."""
        response = client.post(
            "/migration/relational",
            json=create_migration_request_data(
                source_db="postgres",
                target_db=target_db,
            ),
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid target_db" in data["detail"]

    @pytest.mark.parametrize(
        "source_db,target_db",
        [
            ("postgres", "postgres"),
            ("duckdb", "duckdb"),
            ("POSTGRES", "postgres"),
        ],
    )
    def test_should_reject_same_source_and_target_db(self, client, source_db, target_db):
        """Test rejecting when source and target are the same."""
        response = client.post(
            "/migration/relational",
            json=create_migration_request_data(
                source_db=source_db,
                target_db=target_db,
            ),
        )

        assert response.status_code == 400
        data = response.json()
        assert "must be different" in data["detail"].lower()

    @pytest.mark.parametrize("batch_size", [50, 99, 0, -1, 50001, 100000])
    def test_should_reject_invalid_batch_sizes(self, client, batch_size):
        """Test rejecting batch sizes outside valid range."""
        response = client.post(
            "/migration/relational",
            json=create_migration_request_data(
                source_db="postgres",
                target_db="duckdb",
                batch_size=batch_size,
            ),
        )

        # Pydantic validation error
        assert response.status_code == 422

    def test_should_reject_missing_required_fields(self, client):
        """Test rejecting requests with missing required fields."""
        response = client.post(
            "/migration/relational",
            json={},
        )

        assert response.status_code == 422

    def test_should_reject_empty_tables_list_with_null_values(self, client, mock_migration_service):
        """Test handling of null optional fields."""
        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.post(
                "/migration/relational",
                json={
                    "source_db": "postgres",
                    "target_db": "duckdb",
                    "tables": None,
                    "incremental_key": None,
                },
            )

            assert response.status_code == 200


# ============================================================================
# Test Graph Migration Endpoint (POST /migration/graph)
# ============================================================================


class TestGraphMigrationEndpoint:
    """Test POST /migration/graph endpoint."""

    @pytest.mark.parametrize(
        "source_db,target_db",
        [
            ("neo4j", "ladybug"),
            ("ladybug", "neo4j"),
            ("NEO4J", "LADYBUG"),  # Case insensitive
            ("Neo4j", "Ladybug"),  # Mixed case
        ],
    )
    def test_should_start_graph_migration(
        self, client, mock_migration_service, source_db, target_db
    ):
        """Test starting graph migration with valid database pairs."""
        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.post(
                "/migration/graph",
                json=create_migration_request_data(
                    source_db=source_db,
                    target_db=target_db,
                    batch_size=5000,
                ),
            )

            assert response.status_code == 200
            data = response.json()
            assert data["task_id"] == "task_123"
            assert data["status"] == "pending"
            assert "graph migration" in data["message"].lower()

    def test_should_start_graph_migration_with_optional_params(
        self, client, mock_migration_service
    ):
        """Test starting graph migration with optional parameters."""
        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.post(
                "/migration/graph",
                json={
                    "source_db": "neo4j",
                    "target_db": "ladybug",
                    "tables": ["Person", "Organization"],
                    "batch_size": 10000,
                    "mapping_file": "/path/to/graph_mapping.yaml",
                    "strict_mode": True,
                },
            )

            assert response.status_code == 200

    @pytest.mark.parametrize(
        "source_db",
        [
            "postgres",
            "duckdb",
            "mysql",
            "oracle",
            "",
        ],
    )
    def test_should_reject_invalid_source_db_for_graph(self, client, source_db):
        """Test rejecting invalid source database for graph migration."""
        response = client.post(
            "/migration/graph",
            json=create_migration_request_data(
                source_db=source_db,
                target_db="ladybug",
            ),
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid source_db" in data["detail"]

    @pytest.mark.parametrize(
        "target_db",
        [
            "postgres",
            "duckdb",
            "mysql",
            "oracle",
            "",
        ],
    )
    def test_should_reject_invalid_target_db_for_graph(self, client, target_db):
        """Test rejecting invalid target database for graph migration."""
        response = client.post(
            "/migration/graph",
            json=create_migration_request_data(
                source_db="neo4j",
                target_db=target_db,
            ),
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid target_db" in data["detail"]

    @pytest.mark.parametrize(
        "source_db,target_db",
        [
            ("neo4j", "neo4j"),
            ("ladybug", "ladybug"),
            ("NEO4J", "neo4j"),
        ],
    )
    def test_should_reject_same_source_and_target_db_for_graph(self, client, source_db, target_db):
        """Test rejecting when source and target are the same for graph."""
        response = client.post(
            "/migration/graph",
            json=create_migration_request_data(
                source_db=source_db,
                target_db=target_db,
            ),
        )

        assert response.status_code == 400
        data = response.json()
        assert "must be different" in data["detail"].lower()


# ============================================================================
# Test Migration Progress Endpoint (GET /migration/{task_id}/progress)
# ============================================================================


class TestMigrationProgressEndpoint:
    """Test GET /migration/{task_id}/progress endpoint."""

    def test_should_get_progress_for_valid_task(self, client, mock_migration_service):
        """Test getting progress for a valid task."""
        mock_migration_service.get_status.return_value = {
            "status": "running",
            "config": Mock(source_db="postgres", target_db="duckdb"),
            "created_at": datetime.now(),
            "started_at": datetime.now(),
            "progress": {
                "users": {
                    "total": 1000,
                    "migrated": 500,
                    "percent": 50.0,
                    "completed": False,
                    "error": None,
                },
            },
            "result": None,
        }

        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.get("/migration/task_123/progress")

            assert response.status_code == 200
            data = response.json()
            assert data["task_id"] == "task_123"
            assert data["status"] == "running"
            assert data["source_db"] == "postgres"
            assert data["target_db"] == "duckdb"
            assert len(data["items"]) == 1
            assert data["items"][0]["table"] == "users"
            assert data["items"][0]["migrated"] == 500
            assert data["items"][0]["total"] == 1000

    def test_should_reject_invalid_task_id(self, client, mock_migration_service):
        """Test rejecting invalid task ID."""
        mock_migration_service.get_status.return_value = {
            "status": "not_found",
        }

        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.get("/migration/nonexistent_task/progress")

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()

    @pytest.mark.parametrize(
        "status",
        [
            "pending",
            "running",
            "completed",
            "failed",
            "cancelled",
        ],
    )
    def test_should_return_correct_status(self, client, mock_migration_service, status):
        """Test returning correct status for different task states."""
        mock_migration_service.get_status.return_value = {
            "status": status,
            "config": Mock(source_db="postgres", target_db="duckdb"),
            "created_at": datetime.now(),
            "started_at": datetime.now(),
            "progress": {},
            "result": None,
        }

        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.get("/migration/task_123/progress")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == status

    def test_should_return_progress_with_completed_items(self, client, mock_migration_service):
        """Test progress response with completed items."""
        mock_migration_service.get_status.return_value = {
            "status": "completed",
            "config": Mock(source_db="postgres", target_db="duckdb"),
            "created_at": datetime.now(),
            "started_at": datetime.now(),
            "progress": {
                "users": {
                    "total": 1000,
                    "migrated": 1000,
                    "percent": 100.0,
                    "completed": True,
                    "error": None,
                },
                "orders": {
                    "total": 5000,
                    "migrated": 5000,
                    "percent": 100.0,
                    "completed": True,
                    "error": None,
                },
            },
            "result": {
                "total_migrated": 6000,
                "total_expected": 6000,
                "errors": [],
            },
        }

        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.get("/migration/task_123/progress")

            data = response.json()
            assert data["total_migrated"] == 6000
            assert data["total_expected"] == 6000
            assert len(data["items"]) == 2
            assert all(item["status"] == "completed" for item in data["items"])

    def test_should_return_error_for_failed_task(self, client, mock_migration_service):
        """Test error response for failed task."""
        mock_migration_service.get_status.return_value = {
            "status": "failed",
            "config": Mock(source_db="postgres", target_db="duckdb"),
            "created_at": datetime.now(),
            "started_at": datetime.now(),
            "progress": {
                "users": {
                    "total": 1000,
                    "migrated": 100,
                    "percent": 10.0,
                    "completed": False,
                    "error": "Connection timeout",
                },
            },
            "result": None,
            "error": "Migration failed: Connection timeout",
        }

        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.get("/migration/task_123/progress")

            data = response.json()
            assert data["status"] == "failed"
            assert data["error"] == "Migration failed: Connection timeout"
            assert data["items"][0]["error"] == "Connection timeout"

    def test_should_calculate_elapsed_time(self, client, mock_migration_service):
        """Test calculating elapsed time."""
        started_at = datetime.now()
        mock_migration_service.get_status.return_value = {
            "status": "running",
            "config": Mock(source_db="postgres", target_db="duckdb"),
            "created_at": datetime.now(),
            "started_at": started_at,
            "progress": {},
            "result": None,
        }

        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.get("/migration/task_123/progress")

            data = response.json()
            assert data["elapsed_seconds"] >= 0.0


# ============================================================================
# Test Migration Cancel Endpoint (POST /migration/{task_id}/cancel)
# ============================================================================


class TestMigrationCancelEndpoint:
    """Test POST /migration/{task_id}/cancel endpoint."""

    def test_should_cancel_running_migration(self, client, mock_migration_service):
        """Test successfully cancelling a running migration."""
        mock_migration_service.cancel_task.return_value = True

        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.post("/migration/task_123/cancel")

            assert response.status_code == 200
            data = response.json()
            assert data["task_id"] == "task_123"
            assert data["status"] == "cancelled"
            assert "cancelled successfully" in data["message"].lower()

    def test_should_reject_nonexistent_task(self, client, mock_migration_service):
        """Test rejecting cancellation of nonexistent task."""
        mock_migration_service.cancel_task.return_value = False

        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.post("/migration/nonexistent_task/cancel")

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()

    def test_should_reject_completed_task(self, client, mock_migration_service):
        """Test rejecting cancellation of already completed task."""
        mock_migration_service.cancel_task.return_value = False

        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.post("/migration/completed_task/cancel")

            assert response.status_code == 404

    def test_should_reject_pending_task(self, client, mock_migration_service):
        """Test rejecting cancellation of pending task (no engine yet)."""
        # Service returns False if engine doesn't exist yet
        mock_migration_service.cancel_task.return_value = False

        with patch(
            "modules.migration.api.routes.get_migration_service",
            return_value=mock_migration_service,
        ):
            response = client.post("/migration/pending_task/cancel")

            assert response.status_code == 404


# ============================================================================
# Test Mapping Upload Endpoint (POST /migration/mappings)
# ============================================================================


class TestMappingUploadEndpoint:
    """Test POST /migration/mappings endpoint."""

    def test_should_upload_valid_mapping(self, client):
        """Test uploading a valid YAML mapping."""
        yaml_content = """
nodes:
  - source_label: Person
    target_label: User
  - source_label: Organization
    target_label: Company
relations:
  - source_type: WORKS_FOR
    target_type: EMPLOYED_BY
"""
        response = client.post(
            "/migration/mappings",
            json={
                "name": "test_mapping",
                "content": yaml_content,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test_mapping"
        assert len(data["node_mappings"]) == 2
        assert len(data["rel_mappings"]) == 1

    def test_should_upload_mapping_with_empty_nodes(self, client):
        """Test uploading mapping with empty nodes/relations."""
        yaml_content = """
nodes: []
relations: []
"""
        response = client.post(
            "/migration/mappings",
            json={
                "name": "empty_mapping",
                "content": yaml_content,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "empty_mapping"
        assert data["node_mappings"] == []
        assert data["rel_mappings"] == []

    def test_should_upload_complex_mapping(self, client):
        """Test uploading complex mapping with multiple entries."""
        yaml_content = """
nodes:
  - source_label: User
    target_label: Account
    field_mapping:
      name: username
      email: email_address
  - source_label: Product
    target_label: Item
  - source_label: Category
    target_label: Tag
relations:
  - source_type: OWNS
    target_type: HAS
  - source_type: BELONGS_TO
    target_type: CATEGORIZED_AS
  - source_type: FOLLOWS
    target_type: TRACKS
"""
        response = client.post(
            "/migration/mappings",
            json={
                "name": "complex_mapping",
                "content": yaml_content,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["node_mappings"]) == 3
        assert len(data["rel_mappings"]) == 3

    def test_should_reject_invalid_yaml(self, client):
        """Test rejecting invalid YAML content."""
        invalid_yaml = """
nodes:
  - source_label: Person
    target_label: User
  [invalid yaml syntax
"""
        response = client.post(
            "/migration/mappings",
            json={
                "name": "invalid_mapping",
                "content": invalid_yaml,
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid YAML" in data["detail"]

    def test_should_reject_missing_name(self, client):
        """Test rejecting mapping upload without name."""
        response = client.post(
            "/migration/mappings",
            json={
                "content": "nodes: []",
            },
        )

        assert response.status_code == 422

    def test_should_reject_missing_content(self, client):
        """Test rejecting mapping upload without content."""
        response = client.post(
            "/migration/mappings",
            json={
                "name": "test_mapping",
            },
        )

        assert response.status_code == 422


# ============================================================================
# Test Mapping List Endpoint (GET /migration/mappings)
# ============================================================================


class TestMappingListEndpoint:
    """Test GET /migration/mappings endpoint."""

    def test_should_list_empty_mappings(self, client):
        """Test listing mappings when none exist."""
        # Clear the global mappings dict
        from modules.migration.api.routes import _uploaded_mappings

        _uploaded_mappings.clear()

        response = client.get("/migration/mappings")

        assert response.status_code == 200
        data = response.json()
        assert "mappings" in data
        assert len(data["mappings"]) == 0

    def test_should_list_uploaded_mappings(self, client):
        """Test listing previously uploaded mappings."""
        from modules.migration.api.routes import _uploaded_mappings
        from modules.migration.mapping_registry import MappingRegistry

        # Clear and add test mappings
        _uploaded_mappings.clear()

        registry1 = MappingRegistry()
        _uploaded_mappings["mapping1"] = registry1

        registry2 = MappingRegistry()
        _uploaded_mappings["mapping2"] = registry2

        response = client.get("/migration/mappings")

        assert response.status_code == 200
        data = response.json()
        assert len(data["mappings"]) == 2
        names = [m["name"] for m in data["mappings"]]
        assert "mapping1" in names
        assert "mapping2" in names

    def test_should_upload_then_list_mapping(self, client):
        """Test upload then list workflow."""
        from modules.migration.api.routes import _uploaded_mappings

        _uploaded_mappings.clear()

        # Upload a mapping
        yaml_content = """
nodes:
  - source_label: Person
relations:
  - source_type: KNOWS
"""
        upload_response = client.post(
            "/migration/mappings",
            json={
                "name": "test_mapping",
                "content": yaml_content,
            },
        )

        assert upload_response.status_code == 200

        # List mappings
        list_response = client.get("/migration/mappings")

        assert list_response.status_code == 200
        data = list_response.json()
        assert len(data["mappings"]) == 1
        assert data["mappings"][0]["name"] == "test_mapping"

    def test_should_list_mapping_with_correct_structure(self, client):
        """Test listing mapping returns correct structure."""
        from modules.migration.api.routes import _uploaded_mappings
        from modules.migration.mapping_registry import MappingRegistry

        _uploaded_mappings.clear()

        registry = MappingRegistry()
        _uploaded_mappings["test"] = registry

        response = client.get("/migration/mappings")

        data = response.json()
        mapping = data["mappings"][0]
        assert "name" in mapping
        assert "node_mappings" in mapping
        assert "rel_mappings" in mapping
        assert isinstance(mapping["node_mappings"], list)
        assert isinstance(mapping["rel_mappings"], list)

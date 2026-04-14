"""Tests for migration API dependencies."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from modules.migration.api.dependencies import (
    MigrationService,
    get_migration_service,
)
from modules.migration.models import MigrationConfig, MigrationResult


class TestMigrationService:
    """Test MigrationService class."""

    @pytest.fixture
    def mock_container(self):
        """Create a mock container."""
        return Mock()

    @pytest.fixture
    def service(self, mock_container):
        """Create a MigrationService instance with mocked container."""
        return MigrationService(container=mock_container)

    @pytest.fixture
    def mock_config(self):
        """Create a mock migration config."""
        return MigrationConfig(
            source_db="postgres",
            target_db="duckdb",
            tables=["users", "orders"],
            batch_size=1000,
        )

    def test_should_create_task(self, service, mock_config):
        """Test creating migration task."""
        task_id = service.create_task(mock_config)

        assert task_id is not None
        assert len(task_id) == 8  # UUID truncated to 8 chars
        assert task_id in service._tasks
        assert service._tasks[task_id]["config"] == mock_config
        assert service._tasks[task_id]["status"] == "pending"
        assert service._tasks[task_id]["engine"] is None
        assert service._tasks[task_id]["started_at"] is None
        assert isinstance(service._tasks[task_id]["created_at"], datetime)

    def test_should_create_task_with_mapping_file(self, service):
        """Test creating task with mapping file configuration."""
        config = MigrationConfig(
            source_db="neo4j",
            target_db="ladybug",
            mapping_file="/path/to/mapping.yaml",
        )

        task_id = service.create_task(config)

        assert task_id in service._tasks
        assert service._tasks[task_id]["config"].mapping_file == "/path/to/mapping.yaml"

    def test_should_create_unique_task_ids(self, service, mock_config):
        """Test that each task gets a unique ID."""
        task_id_1 = service.create_task(mock_config)
        task_id_2 = service.create_task(mock_config)

        assert task_id_1 != task_id_2

    @pytest.mark.asyncio
    async def test_should_run_migration_successfully(self, service, mock_config):
        """Test running migration successfully."""
        # Create task first
        task_id = service.create_task(mock_config)

        # Mock MigrationEngine
        mock_result = MigrationResult(
            config=mock_config,
            items=[],
            started_at=datetime.now(),
            completed_at=datetime.now(),
            status="success",
            total_migrated=100,
            total_expected=100,
        )

        with patch("modules.migration.engine.MigrationEngine") as mock_engine_class:
            mock_engine = AsyncMock()
            mock_engine.run = AsyncMock(return_value=mock_result)
            mock_engine_class.return_value = mock_engine

            # Run migration
            await service.run_migration(task_id)

            # Verify task status
            assert service._tasks[task_id]["status"] == "completed"
            assert service._tasks[task_id]["started_at"] is not None
            assert task_id in service._results
            assert service._results[task_id] == mock_result

            # Verify engine was created and run
            mock_engine_class.assert_called_once()
            mock_engine.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_run_migration_with_mapping_file(self, service, mock_container):
        """Test running migration with mapping file."""
        config = MigrationConfig(
            source_db="neo4j",
            target_db="ladybug",
            mapping_file="/path/to/mapping.yaml",
        )

        task_id = service.create_task(config)

        mock_result = MigrationResult(
            config=config,
            items=[],
            started_at=datetime.now(),
            completed_at=datetime.now(),
            status="success",
            total_migrated=50,
            total_expected=50,
        )

        with (
            patch("modules.migration.mapping_registry.MappingRegistry") as mock_registry_class,
            patch("modules.migration.engine.MigrationEngine") as mock_engine_class,
        ):
            mock_registry = Mock()
            mock_registry_class.return_value = mock_registry

            mock_engine = AsyncMock()
            mock_engine.run = AsyncMock(return_value=mock_result)
            mock_engine_class.return_value = mock_engine

            await service.run_migration(task_id)

            # Verify mapping registry was created and loaded
            mock_registry_class.assert_called_once()
            mock_registry.load.assert_called_once_with("/path/to/mapping.yaml")

    @pytest.mark.asyncio
    async def test_should_run_migration_without_task(self, service):
        """Test running migration with non-existent task."""
        # Should not raise exception, just return silently
        await service.run_migration("nonexistent_task")

    @pytest.mark.asyncio
    async def test_should_handle_migration_failure(self, service, mock_config):
        """Test handling migration failure."""
        task_id = service.create_task(mock_config)

        with patch("modules.migration.engine.MigrationEngine") as mock_engine_class:
            mock_engine = AsyncMock()
            mock_engine.run = AsyncMock(side_effect=Exception("Database connection failed"))
            mock_engine_class.return_value = mock_engine

            # Run migration and expect exception
            with pytest.raises(Exception, match="Database connection failed"):
                await service.run_migration(task_id)

            # Verify task status is failed
            assert service._tasks[task_id]["status"] == "failed"
            assert "error" in service._tasks[task_id]
            assert "Database connection failed" in service._tasks[task_id]["error"]

    @pytest.mark.asyncio
    async def test_should_handle_migration_with_empty_tables(self, service):
        """Test migration with no tables specified."""
        config = MigrationConfig(
            source_db="postgres",
            target_db="duckdb",
            tables=None,  # No tables specified
        )

        task_id = service.create_task(config)

        mock_result = MigrationResult(
            config=config,
            items=[],
            started_at=datetime.now(),
            completed_at=datetime.now(),
            status="success",
            total_migrated=0,
            total_expected=0,
        )

        with patch("modules.migration.engine.MigrationEngine") as mock_engine_class:
            mock_engine = AsyncMock()
            mock_engine.run = AsyncMock(return_value=mock_result)
            mock_engine_class.return_value = mock_engine

            await service.run_migration(task_id)

            assert service._tasks[task_id]["status"] == "completed"

    def test_should_cancel_running_task(self, service, mock_config):
        """Test cancelling a running migration task."""
        task_id = service.create_task(mock_config)

        # Manually set up a running task with engine
        service._tasks[task_id]["status"] = "running"
        mock_engine = Mock()
        mock_engine.cancel = Mock()
        service._tasks[task_id]["engine"] = mock_engine

        result = service.cancel_task(task_id)

        assert result is True
        assert service._tasks[task_id]["status"] == "cancelled"
        mock_engine.cancel.assert_called_once()

    def test_should_not_cancel_nonexistent_task(self, service):
        """Test cancelling non-existent task."""
        result = service.cancel_task("nonexistent_task")

        assert result is False

    def test_should_not_cancel_task_without_engine(self, service, mock_config):
        """Test cancelling task that has no engine."""
        task_id = service.create_task(mock_config)

        # Task is created but not started, so no engine
        result = service.cancel_task(task_id)

        assert result is False
        assert service._tasks[task_id]["status"] == "pending"

    def test_should_get_status_of_pending_task(self, service, mock_config):
        """Test getting status of pending task."""
        task_id = service.create_task(mock_config)

        status = service.get_status(task_id)

        assert status["status"] == "pending"
        assert status["config"] == mock_config
        assert "created_at" in status
        assert status["started_at"] is None
        assert "progress" not in status
        assert "result" not in status

    def test_should_get_status_of_running_task(self, service, mock_config):
        """Test getting status of running task with progress."""
        task_id = service.create_task(mock_config)
        service._tasks[task_id]["status"] = "running"
        service._tasks[task_id]["started_at"] = datetime.now()

        # Mock engine with progress
        mock_engine = Mock()
        mock_engine.get_progress_dict = Mock(
            return_value={
                "users": {"total": 1000, "migrated": 500, "status": "running"},
                "orders": {"total": 2000, "migrated": 0, "status": "pending"},
            }
        )
        service._tasks[task_id]["engine"] = mock_engine

        status = service.get_status(task_id)

        assert status["status"] == "running"
        assert "progress" in status
        assert status["progress"]["users"]["migrated"] == 500
        assert "result" not in status

    def test_should_get_status_of_completed_task(self, service, mock_config):
        """Test getting status of completed task with result."""
        task_id = service.create_task(mock_config)
        service._tasks[task_id]["status"] = "completed"

        # Add result
        mock_result = MigrationResult(
            config=mock_config,
            items=[],
            started_at=datetime.now(),
            completed_at=datetime.now(),
            status="success",
            total_migrated=1500,
            total_expected=1500,
        )
        service._results[task_id] = mock_result

        status = service.get_status(task_id)

        assert status["status"] == "completed"
        assert "result" in status
        assert status["result"]["total_migrated"] == 1500
        assert status["result"]["total_expected"] == 1500
        assert status["result"]["errors"] == []

    def test_should_get_status_of_failed_task(self, service, mock_config):
        """Test getting status of failed task."""
        task_id = service.create_task(mock_config)
        service._tasks[task_id]["status"] = "failed"
        service._tasks[task_id]["error"] = "Connection timeout"

        status = service.get_status(task_id)

        assert status["status"] == "failed"
        assert "error" not in status  # Error is in task dict, not status response

    def test_should_get_status_of_nonexistent_task(self, service):
        """Test getting status of non-existent task."""
        status = service.get_status("nonexistent_task")

        assert status == {"status": "not_found"}

    def test_should_get_status_with_cancelled_task(self, service, mock_config):
        """Test getting status of cancelled task."""
        task_id = service.create_task(mock_config)
        service._tasks[task_id]["status"] = "cancelled"

        status = service.get_status(task_id)

        assert status["status"] == "cancelled"

    def test_should_manage_multiple_tasks(self, service):
        """Test managing multiple tasks simultaneously."""
        config_1 = MigrationConfig(source_db="postgres", target_db="duckdb")
        config_2 = MigrationConfig(source_db="neo4j", target_db="ladybug")

        task_id_1 = service.create_task(config_1)
        task_id_2 = service.create_task(config_2)

        assert len(service._tasks) == 2
        assert task_id_1 in service._tasks
        assert task_id_2 in service._tasks
        assert service._tasks[task_id_1]["config"].source_db == "postgres"
        assert service._tasks[task_id_2]["config"].source_db == "neo4j"

        # Get status of both tasks
        status_1 = service.get_status(task_id_1)
        status_2 = service.get_status(task_id_2)

        assert status_1["status"] == "pending"
        assert status_2["status"] == "pending"


class TestGetMigrationService:
    """Test get_migration_service dependency function."""

    def test_should_return_migration_service_instance(self):
        """Test that get_migration_service returns MigrationService instance."""
        mock_container = Mock()

        service = get_migration_service(container=mock_container)

        assert isinstance(service, MigrationService)
        assert service._container == mock_container

    def test_should_create_new_instance_each_call(self):
        """Test that each call creates a new MigrationService instance."""
        mock_container = Mock()

        service_1 = get_migration_service(container=mock_container)
        service_2 = get_migration_service(container=mock_container)

        assert service_1 is not service_2
        assert service_1._container == service_2._container

    def test_should_initialize_with_empty_tasks(self):
        """Test that service is initialized with empty tasks dict."""
        mock_container = Mock()

        service = get_migration_service(container=mock_container)

        assert service._tasks == {}
        assert service._results == {}

    def test_should_work_with_mock_container(self):
        """Test that service works with mocked container."""
        mock_container = MagicMock()

        service = get_migration_service(container=mock_container)

        # Should be able to create tasks
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        task_id = service.create_task(config)

        assert task_id is not None
        assert task_id in service._tasks

    def test_should_accept_different_container_types(self):
        """Test that service accepts different container implementations."""
        # Test with Mock
        mock_container = Mock()
        service_1 = get_migration_service(container=mock_container)
        assert isinstance(service_1, MigrationService)

        # Test with MagicMock
        fake_container = MagicMock()
        service_2 = get_migration_service(container=fake_container)
        assert isinstance(service_2, MigrationService)

        # Test with dict (edge case)
        dict_container = {"key": "value"}
        service_3 = get_migration_service(container=dict_container)
        assert isinstance(service_3, MigrationService)


class TestMigrationServiceEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def mock_container(self):
        """Create a mock container."""
        return Mock()

    @pytest.fixture
    def service(self, mock_container):
        """Create a MigrationService instance."""
        return MigrationService(container=mock_container)

    def test_should_handle_rapid_task_creation(self, service):
        """Test creating many tasks rapidly."""
        configs = [MigrationConfig(source_db="postgres", target_db="duckdb") for _ in range(10)]

        task_ids = []
        for config in configs:
            task_id = service.create_task(config)
            task_ids.append(task_id)

        # All task IDs should be unique
        assert len(set(task_ids)) == 10
        assert len(service._tasks) == 10

    def test_should_handle_special_characters_in_config(self, service):
        """Test config with special characters."""
        config = MigrationConfig(
            source_db="postgres",
            target_db="duckdb",
            tables=["users_data", "order-items", "product@category"],
            mapping_file="/path/with spaces/mapping.yaml",
        )

        task_id = service.create_task(config)

        assert task_id in service._tasks
        assert service._tasks[task_id]["config"] == config

    @pytest.mark.asyncio
    async def test_should_handle_concurrent_task_status_checks(self, service):
        """Test concurrent status checks don't interfere."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        task_id = service.create_task(config)

        # Simulate multiple status checks
        status_1 = service.get_status(task_id)
        status_2 = service.get_status(task_id)
        status_3 = service.get_status(task_id)

        # All should return the same status
        assert status_1 == status_2 == status_3
        assert status_1["status"] == "pending"

    @pytest.mark.asyncio
    async def test_should_handle_migration_error_variations(self, service):
        """Test different types of migration errors."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        task_id = service.create_task(config)

        error_cases = [
            ValueError("Invalid data type"),
            RuntimeError("Connection refused"),
            TimeoutError("Operation timed out"),
            Exception("Unknown error"),
        ]

        for error in error_cases:
            # Create fresh task for each error case
            fresh_task_id = service.create_task(config)

            with patch("modules.migration.engine.MigrationEngine") as mock_engine_class:
                mock_engine = AsyncMock()
                mock_engine.run = AsyncMock(side_effect=error)
                mock_engine_class.return_value = mock_engine

                with pytest.raises(type(error)):
                    await service.run_migration(fresh_task_id)

                assert service._tasks[fresh_task_id]["status"] == "failed"
                assert "error" in service._tasks[fresh_task_id]

    def test_should_handle_empty_result_retrieval(self, service):
        """Test getting result for task without result."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        task_id = service.create_task(config)

        status = service.get_status(task_id)

        assert "result" not in status

    def test_should_preserve_task_history(self, service):
        """Test that task history is preserved after completion."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        task_id = service.create_task(config)

        # Run migration
        mock_result = MigrationResult(
            config=config,
            items=[],
            started_at=datetime.now(),
            completed_at=datetime.now(),
            status="success",
            total_migrated=100,
            total_expected=100,
        )

        with patch("modules.migration.engine.MigrationEngine") as mock_engine_class:
            mock_engine = AsyncMock()
            mock_engine.run = AsyncMock(return_value=mock_result)
            mock_engine_class.return_value = mock_engine

            import asyncio

            asyncio.get_event_loop().run_until_complete(service.run_migration(task_id))

        # Task should still exist in history
        assert task_id in service._tasks
        assert task_id in service._results
        assert service._tasks[task_id]["status"] == "completed"

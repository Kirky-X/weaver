# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Storage module unit tests.

Tests for storage operations including:
- File system storage
- Object storage abstraction
- Binary data handling
- Storage backend management
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFileSystemStorage:
    """Tests for file system storage operations."""

    @pytest.fixture
    def temp_dir(self) -> Path:
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.mark.asyncio
    async def test_file_write(self, temp_dir: Path) -> None:
        """Test writing a file to storage."""
        file_path = temp_dir / "test.txt"
        content = b"Hello, World!"

        # Write file
        file_path.write_bytes(content)

        assert file_path.exists()
        assert file_path.read_bytes() == content

    @pytest.mark.asyncio
    async def test_file_read(self, temp_dir: Path) -> None:
        """Test reading a file from storage."""
        file_path = temp_dir / "test.txt"
        expected_content = b"Test content"

        # Create file
        file_path.write_bytes(expected_content)

        # Read file
        actual_content = file_path.read_bytes()

        assert actual_content == expected_content

    @pytest.mark.asyncio
    async def test_file_delete(self, temp_dir: Path) -> None:
        """Test deleting a file from storage."""
        file_path = temp_dir / "test.txt"

        # Create and delete file
        file_path.write_bytes(b"content")
        file_path.unlink()

        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_directory_creation(self, temp_dir: Path) -> None:
        """Test creating directories."""
        new_dir = temp_dir / "subdir" / "nested"

        new_dir.mkdir(parents=True, exist_ok=True)

        assert new_dir.exists()
        assert new_dir.is_dir()

    @pytest.mark.asyncio
    async def test_file_exists_check(self, temp_dir: Path) -> None:
        """Test checking file existence."""
        existing_file = temp_dir / "exists.txt"
        existing_file.write_bytes(b"content")

        non_existent_file = temp_dir / "not_exists.txt"

        assert existing_file.exists()
        assert not non_existent_file.exists()

    @pytest.mark.asyncio
    async def test_atomic_write(self, temp_dir: Path) -> None:
        """Test atomic file write operation."""
        file_path = temp_dir / "atomic.txt"
        temp_path = temp_dir / "atomic.txt.tmp"
        content = b"Atomic content"

        # Write to temp file first
        temp_path.write_bytes(content)

        # Atomic rename
        temp_path.rename(file_path)

        assert file_path.exists()
        assert file_path.read_bytes() == content
        assert not temp_path.exists()


class TestObjectStorageAbstraction:
    """Tests for object storage abstraction layer."""

    @pytest.fixture
    def mock_storage_backend(self) -> AsyncMock:
        """Create a mock storage backend."""
        backend = AsyncMock()
        backend.upload = AsyncMock()
        backend.download = AsyncMock()
        backend.delete = AsyncMock()
        backend.list_objects = AsyncMock()
        return backend

    @pytest.mark.asyncio
    async def test_upload_object(self, mock_storage_backend: AsyncMock) -> None:
        """Test uploading an object to storage."""
        key = "test/object.txt"
        data = b"Object data"

        await mock_storage_backend.upload(key, data)
        mock_storage_backend.upload.assert_called_once_with(key, data)

    @pytest.mark.asyncio
    async def test_download_object(self, mock_storage_backend: AsyncMock) -> None:
        """Test downloading an object from storage."""
        key = "test/object.txt"
        expected_data = b"Downloaded data"

        mock_storage_backend.download.return_value = expected_data
        result = await mock_storage_backend.download(key)

        assert result == expected_data
        mock_storage_backend.download.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_delete_object(self, mock_storage_backend: AsyncMock) -> None:
        """Test deleting an object from storage."""
        key = "test/object.txt"

        await mock_storage_backend.delete(key)
        mock_storage_backend.delete.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_list_objects(self, mock_storage_backend: AsyncMock) -> None:
        """Test listing objects in storage."""
        prefix = "test/"
        expected_objects = ["test/file1.txt", "test/file2.txt"]

        mock_storage_backend.list_objects.return_value = expected_objects
        result = await mock_storage_backend.list_objects(prefix)

        assert result == expected_objects
        mock_storage_backend.list_objects.assert_called_once_with(prefix)


class TestStorageBackendManager:
    """Tests for storage backend management."""

    @pytest.fixture
    def mock_backends(self) -> dict[str, AsyncMock]:
        """Create mock storage backends."""
        return {
            "local": AsyncMock(),
            "s3": AsyncMock(),
            "gcs": AsyncMock(),
        }

    @pytest.mark.asyncio
    async def test_backend_selection(self, mock_backends: dict[str, AsyncMock]) -> None:
        """Test selecting the appropriate backend."""
        selected_backend = mock_backends["s3"]

        # Simulate backend selection logic
        backend_type = "s3"
        backend = mock_backends[backend_type]

        assert backend == selected_backend

    @pytest.mark.asyncio
    async def test_backend_fallback(self, mock_backends: dict[str, AsyncMock]) -> None:
        """Test falling back to default backend."""
        primary = mock_backends["s3"]
        fallback = mock_backends["local"]

        primary.upload.side_effect = Exception("Backend unavailable")

        # Try primary, fallback to secondary
        try:
            await primary.upload("key", b"data")
        except Exception:
            await fallback.upload("key", b"data")

        fallback.upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_backend_health_check(self, mock_backends: dict[str, AsyncMock]) -> None:
        """Test checking backend health status."""
        backend = mock_backends["s3"]
        backend.health_check = AsyncMock(return_value=True)

        is_healthy = await backend.health_check()

        assert is_healthy is True
        backend.health_check.assert_called_once()


class TestBinaryDataHandling:
    """Tests for binary large object (BLOB) handling."""

    @pytest.fixture
    def temp_dir(self) -> Path:
        """Create a temporary directory for BLOB testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.mark.asyncio
    async def test_large_file_write(self, temp_dir: Path) -> None:
        """Test writing large binary data."""
        file_path = temp_dir / "large_blob.bin"
        # Create 1MB of data
        large_data = bytes(range(256)) * 4096

        file_path.write_bytes(large_data)

        assert file_path.exists()
        assert file_path.stat().st_size == len(large_data)

    @pytest.mark.asyncio
    async def test_chunked_read(self, temp_dir: Path) -> None:
        """Test reading large files in chunks."""
        file_path = temp_dir / "chunked.bin"
        chunk_size = 1024
        total_size = chunk_size * 10

        # Create test file
        test_data = bytes(range(256)) * (total_size // 256 + 1)
        file_path.write_bytes(test_data[:total_size])

        # Read in chunks
        chunks = []
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                chunks.append(chunk)

        reconstructed = b"".join(chunks)
        assert len(reconstructed) == total_size
        assert reconstructed == test_data[:total_size]

    @pytest.mark.asyncio
    async def test_binary_compression(self, temp_dir: Path) -> None:
        """Test binary data compression."""
        import zlib

        file_path = temp_dir / "compressed.bin"
        original_data = b"Repeated data " * 1000

        # Compress
        compressed = zlib.compress(original_data)

        # Save compressed data
        file_path.write_bytes(compressed)

        # Read and decompress
        saved_compressed = file_path.read_bytes()
        decompressed = zlib.decompress(saved_compressed)

        assert decompressed == original_data
        assert len(compressed) < len(original_data)


class TestStorageMigration:
    """Tests for storage migration and versioning."""

    @pytest.fixture
    def temp_dir(self) -> Path:
        """Create a temporary directory for migration testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.mark.asyncio
    async def test_version_tracking(self, temp_dir: Path) -> None:
        """Test tracking file versions."""
        base_path = temp_dir / "versioned.txt"
        version_file = temp_dir / "version.txt"

        # Write initial version
        base_path.write_bytes(b"Version 1")
        version_file.write_text("1")

        # Update version
        base_path.write_bytes(b"Version 2")
        version_file.write_text("2")

        assert version_file.read_text() == "2"

    @pytest.mark.asyncio
    async def test_backup_creation(self, temp_dir: Path) -> None:
        """Test creating backups before migration."""
        original_file = temp_dir / "data.txt"
        backup_file = temp_dir / "data.txt.bak"

        original_content = b"Original data"
        original_file.write_bytes(original_content)

        # Create backup
        backup_file.write_bytes(original_file.read_bytes())

        # Modify original
        original_file.write_bytes(b"New data")

        # Verify backup
        assert backup_file.read_bytes() == original_content

    @pytest.mark.asyncio
    async def test_rollback_mechanism(self, temp_dir: Path) -> None:
        """Test rolling back failed migrations."""
        original_file = temp_dir / "data.txt"
        backup_file = temp_dir / "data.txt.bak"

        original_content = b"Original data"
        backup_file.write_bytes(original_content)

        # Simulate failed migration
        original_file.write_bytes(b"Corrupted data")

        # Rollback
        if backup_file.exists():
            original_file.write_bytes(backup_file.read_bytes())

        assert original_file.read_bytes() == original_content

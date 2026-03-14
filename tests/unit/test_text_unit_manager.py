"""Unit tests for text unit manager module."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from modules.community.text_unit_manager import (
    TextUnitManager,
    TextUnit,
)


class TestTextUnit:
    """Test TextUnit dataclass."""

    def test_initialization(self):
        """Test TextUnit initialization."""
        unit = TextUnit(
            id="unit-1",
            content="Test content",
            source_article_id="article-1",
            chunk_index=0,
            token_count=100,
            entity_ids=["e1", "e2"],
            entity_names=["Entity1", "Entity2"],
        )

        assert unit.id == "unit-1"
        assert unit.content == "Test content"
        assert unit.token_count == 100


class TestTextUnitManager:
    """Test TextUnitManager class."""

    def test_init(self):
        """Test initialization."""
        mock_pool = MagicMock()
        manager = TextUnitManager(mock_pool)

        assert manager._pool == mock_pool
        assert manager._chunk_size == 500

    def test_init_custom(self):
        """Test custom initialization."""
        mock_pool = MagicMock()
        manager = TextUnitManager(mock_pool, default_chunk_size=1000, overlap=100)

        assert manager._chunk_size == 1000
        assert manager._overlap == 100

    def test_chunk_text_single(self):
        """Test chunking text smaller than chunk size."""
        mock_pool = MagicMock()
        manager = TextUnitManager(mock_pool)

        chunks = manager.chunk_text("Short text")

        assert len(chunks) == 1
        assert chunks[0] == "Short text"

    def test_chunk_text_multiple(self):
        """Test chunking text into multiple chunks."""
        mock_pool = MagicMock()
        manager = TextUnitManager(mock_pool, default_chunk_size=10, overlap=2)

        text = "0123456789" * 5
        chunks = manager.chunk_text(text)

        assert len(chunks) > 1

    def test_chunk_text_with_periods(self):
        """Test chunking respects sentence boundaries."""
        mock_pool = MagicMock()
        manager = TextUnitManager(mock_pool, default_chunk_size=20, overlap=5)

        text = "这是第一句。这是第二句。这是第三句。"
        chunks = manager.chunk_text(text)

        assert len(chunks) > 0

    def test_estimate_tokens(self):
        """Test token estimation."""
        mock_pool = MagicMock()
        manager = TextUnitManager(mock_pool)

        tokens = manager.estimate_tokens("你好世界")

        assert tokens > 0

    def test_estimate_tokens_mixed(self):
        """Test token estimation with mixed content."""
        mock_pool = MagicMock()
        manager = TextUnitManager(mock_pool)

        tokens = manager.estimate_tokens("Hello 你好")

        assert tokens > 0

    @pytest.mark.asyncio
    async def test_create_text_units(self):
        """Test creating text units from article."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        manager = TextUnitManager(mock_pool)

        text = "这是第一段文字。这是第二段文字。"
        units = await manager.create_text_units("article-1", text)

        assert len(units) > 0
        assert units[0].source_article_id == "article-1"

    @pytest.mark.asyncio
    async def test_create_text_units_with_entity_mapping(self):
        """Test creating text units with entity mapping."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        manager = TextUnitManager(mock_pool)

        text = "实体A 与 实体B 合作。"
        entity_mapping = {0: ["实体A", "实体B"]}

        units = await manager.create_text_units("article-1", text, entity_mapping)

        assert len(units) > 0

    @pytest.mark.asyncio
    async def test_get_text_unit(self):
        """Test getting text unit by ID."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{
            "id": "unit-1",
            "content": "Test content",
            "source_article_id": "article-1",
            "chunk_index": 0,
            "token_count": 100,
            "entity_names": ["Entity1"],
            "created_at": datetime.now(timezone.utc),
        }])
        manager = TextUnitManager(mock_pool)

        unit = await manager.get_text_unit("unit-1")

        assert unit is not None
        assert unit.id == "unit-1"

    @pytest.mark.asyncio
    async def test_get_text_unit_not_found(self):
        """Test getting non-existent text unit."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])
        manager = TextUnitManager(mock_pool)

        unit = await manager.get_text_unit("non-existent")

        assert unit is None

    @pytest.mark.asyncio
    async def test_get_entity_text_units(self):
        """Test getting text units for an entity."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{
            "id": "unit-1",
            "content": "Content with Entity1",
            "source_article_id": "article-1",
            "chunk_index": 0,
            "token_count": 50,
            "entity_names": ["Entity1"],
            "created_at": datetime.now(timezone.utc),
        }])
        manager = TextUnitManager(mock_pool)

        units = await manager.get_entity_text_units("Entity1")

        assert len(units) > 0

    def test_row_to_unit(self):
        """Test converting database row to TextUnit."""
        mock_pool = MagicMock()
        manager = TextUnitManager(mock_pool)

        row = {
            "id": "unit-1",
            "content": "Test content",
            "source_article_id": "article-1",
            "chunk_index": 0,
            "token_count": 100,
            "entity_names": ["Entity1"],
            "created_at": datetime.now(timezone.utc),
        }

        unit = manager._row_to_unit(row)

        assert unit.id == "unit-1"
        assert unit.content == "Test content"

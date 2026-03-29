# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for RelationTypeNormalizer module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest

from core.db.models import RelationType, RelationTypeAlias, UnknownRelationType
from modules.graph_store.relation_type_normalizer import (
    NormalizedRelation,
    RelationTypeNormalizer,
)


def _make_mock_relation_type(
    id: int,
    name: str,
    name_en: str,
    category: str,
    is_symmetric: bool,
    sort_order: int,
    aliases: list[str] | None = None,
) -> MagicMock:
    """Create a mock RelationType object for testing.

    Args:
        id: Relation type ID.
        name: Chinese name.
        name_en: English name.
        category: Category name.
        is_symmetric: Whether symmetric.
        sort_order: Sort order.
        aliases: List of alias strings.

    Returns:
        Mock RelationType object with configured attributes.
    """
    rt = MagicMock(spec=RelationType)
    rt.id = id
    rt.name = name
    rt.name_en = name_en
    rt.category = category
    rt.is_symmetric = is_symmetric
    rt.is_active = True
    rt.sort_order = sort_order
    rt.description = f"{name}关系的描述"

    # Mock aliases as a list of mock objects
    alias_objects = []
    if aliases:
        for alias in aliases:
            alias_obj = MagicMock(spec=RelationTypeAlias)
            alias_obj.alias = alias
            alias_objects.append(alias_obj)

    rt.aliases = alias_objects
    return rt


def _make_mock_pool(
    relation_types: list[MagicMock] | None = None,
    unknown_record: UnknownRelationType | MagicMock | None = None,
) -> MagicMock:
    """Build a mock PostgresPool for testing.

    Args:
        relation_types: List of mock RelationType objects to return from queries.
        unknown_record: UnknownRelationType object for unknown queries.

    Returns:
        Mock PostgresPool with configured session behavior.
    """
    if relation_types is None:
        relation_types = []

    _relation_types = relation_types
    _unknown_record = unknown_record

    async def mock_execute(query, params=None):
        result = MagicMock()
        query_str = str(query).lower()

        if "relation_types" in query_str and "select" in query_str:
            # 查询关系类型 - 返回 scalars() 模拟
            mock_scalars = MagicMock()
            mock_scalars.all = MagicMock(return_value=_relation_types)
            result.scalars = MagicMock(return_value=mock_scalars)
        elif "unknown_relation_types" in query_str:
            # 查询未知关系类型 - 返回配置的记录或 None
            result.scalar_one_or_none = MagicMock(return_value=_unknown_record)
        else:
            # 默认空结果
            mock_scalars = MagicMock()
            mock_scalars.all = MagicMock(return_value=[])
            result.scalars = MagicMock(return_value=mock_scalars)

        return result

    def _create_mock_session():
        """Create a new mock session for each session() call."""
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(wraps=mock_execute)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        return mock_session

    mock_pool = MagicMock()
    mock_session = _create_mock_session()

    # Make session() return a new context manager with a fresh session each time
    mock_pool.session.return_value.__aenter__.return_value = mock_session

    return mock_pool


class TestRelationTypeNormalizer:
    """Tests for RelationTypeNormalizer."""

    @pytest.fixture
    def normalizer(self):
        """Create RelationTypeNormalizer with mock pool for each test."""
        mock_pool = MagicMock()
        return RelationTypeNormalizer(mock_pool)

    # ── normalize() tests ───────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_normalize_exact_alias(self, normalizer):
        """Test normalize() with exact alias match."""
        relation_types = [
            _make_mock_relation_type(
                id=1,
                name="合作",
                name_en="PARTNERS_WITH",
                category="商业",
                is_symmetric=True,
                sort_order=1,
                aliases=["战略合作", "联合"],
            )
        ]
        normalizer._pool = _make_mock_pool(relation_types)

        result = await normalizer.normalize("战略合作")

        assert result.raw_type == "战略合作"
        assert result.name == "合作"
        assert result.name_en == "PARTNERS_WITH"
        assert result.is_symmetric is True
        assert result.is_unknown is False

    @pytest.mark.asyncio
    async def test_normalize_suffix_cleaning(self, normalizer):
        """Test normalize() with suffix cleaning."""
        relation_types = [
            _make_mock_relation_type(
                id=1,
                name="合作",
                name_en="PARTNERS_WITH",
                category="商业",
                is_symmetric=True,
                sort_order=1,
                aliases=["合作开发"],
            )
        ]
        normalizer._pool = _make_mock_pool(relation_types)

        result = await normalizer.normalize("合作开发了")

        assert result.raw_type == "合作开发了"
        assert result.name == "合作"
        assert result.name_en == "PARTNERS_WITH"
        assert result.is_unknown is False

    @pytest.mark.asyncio
    async def test_normalize_standard_name(self, normalizer):
        """Test normalize() with standard name match."""
        relation_types = [
            _make_mock_relation_type(
                id=1,
                name="合作",
                name_en="PARTNERS_WITH",
                category="商业",
                is_symmetric=True,
                sort_order=1,
                aliases=None,
            )
        ]
        normalizer._pool = _make_mock_pool(relation_types)

        result = await normalizer.normalize("合作")

        assert result.raw_type == "合作"
        assert result.name == "合作"
        assert result.name_en == "PARTNERS_WITH"
        assert result.is_unknown is False

    @pytest.mark.asyncio
    async def test_normalize_name_en(self, normalizer):
        """Test normalize() with English name match."""
        relation_types = [
            _make_mock_relation_type(
                id=1,
                name="合作",
                name_en="PARTNERS_WITH",
                category="商业",
                is_symmetric=True,
                sort_order=1,
                aliases=None,
            )
        ]
        normalizer._pool = _make_mock_pool(relation_types)

        result = await normalizer.normalize("PARTNERS_WITH")

        assert result.raw_type == "PARTNERS_WITH"
        assert result.name == "合作"
        assert result.name_en == "PARTNERS_WITH"
        assert result.is_unknown is False

    @pytest.mark.asyncio
    async def test_normalize_name_en_case_insensitive(self, normalizer):
        """Test normalize() with lowercase English name."""
        relation_types = [
            _make_mock_relation_type(
                id=1,
                name="合作",
                name_en="PARTNERS_WITH",
                category="商业",
                is_symmetric=True,
                sort_order=1,
                aliases=None,
            )
        ]
        normalizer._pool = _make_mock_pool(relation_types)

        result = await normalizer.normalize("partners_with")

        assert result.raw_type == "partners_with"
        assert result.name == "合作"
        assert result.name_en == "PARTNERS_WITH"
        assert result.is_unknown is False

    @pytest.mark.asyncio
    async def test_normalize_unknown(self, normalizer):
        """Test normalize() with unknown relation type."""
        normalizer._pool = _make_mock_pool([])

        result = await normalizer.normalize("深度绑定")

        assert result.raw_type == "深度绑定"
        assert result.name is None
        assert result.name_en is None
        assert result.is_symmetric is False
        assert result.is_unknown is True

    @pytest.mark.asyncio
    async def test_normalize_empty_string(self, normalizer):
        """Test normalize() with empty string."""
        normalizer._pool = _make_mock_pool([])

        result = await normalizer.normalize("")

        assert result.raw_type == ""
        assert result.name is None
        assert result.name_en is None

    # ── record_unknown() tests ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_record_unknown_new(self, normalizer):
        """Test record_unknown() inserts new record."""
        # Create a fresh normalizer for this test to avoid state leakage
        mock_pool = MagicMock()
        mock_session = MagicMock()

        # Mock execute to return None (no existing record)
        async def mock_execute(query, params=None):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=None)
            return result

        mock_session.execute = AsyncMock(wraps=mock_execute)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        fresh_normalizer = RelationTypeNormalizer(mock_pool)

        await fresh_normalizer.record_unknown("深度绑定", context="测试上下文")

        # Verify session.add was called
        assert mock_session.add.call_count > 0
        assert mock_session.commit.call_count > 0

    @pytest.mark.asyncio
    async def test_record_unknown_existing(self, normalizer):
        """Test record_unknown() updates existing record."""
        # Create existing unknown record
        existing_unknown = MagicMock(spec=UnknownRelationType)
        existing_unknown.id = 1
        existing_unknown.hit_count = 3

        normalizer._pool = _make_mock_pool(unknown_record=existing_unknown)

        await normalizer.record_unknown("深度绑定", context="新上下文")

        # Verify execute was called for update
        session = normalizer._pool.session.return_value.__aenter__.return_value
        assert session.execute.call_count > 0
        assert session.commit.call_count > 0

    @pytest.mark.asyncio
    async def test_record_unknown_with_invalid_uuid(self, normalizer):
        """Test record_unknown() handles invalid UUID string."""
        normalizer._pool = _make_mock_pool(unknown_record=None)

        # Should not raise exception
        await normalizer.record_unknown("测试关系", article_id="not-a-uuid")

        # Verify session operations completed
        session = normalizer._pool.session.return_value.__aenter__.return_value
        assert session.add.call_count > 0 or session.execute.call_count > 0

    @pytest.mark.asyncio
    async def test_record_unknown_empty_raw_type(self, normalizer):
        """Test record_unknown() with empty raw_type."""
        normalizer._pool = _make_mock_pool(unknown_record=None)

        # Should return early without database operations
        await normalizer.record_unknown("")

        session = normalizer._pool.session.return_value.__aenter__.return_value
        assert session.add.call_count == 0
        assert session.execute.call_count == 0

    @pytest.mark.asyncio
    async def test_record_unknown_with_valid_uuid(self, normalizer):
        """Test record_unknown() with valid UUID string."""
        mock_pool = MagicMock()
        mock_session = MagicMock()

        # Mock execute to return None (no existing record)
        async def mock_execute(query, params=None):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=None)
            return result

        mock_session.execute = AsyncMock(wraps=mock_execute)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        fresh_normalizer = RelationTypeNormalizer(mock_pool)
        test_uuid = uuid4()

        await fresh_normalizer.record_unknown("测试关系", article_id=str(test_uuid))

        assert mock_session.add.call_count > 0

    # ── get_all_active() tests ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_all_active(self, normalizer):
        """Test get_all_active() returns sorted relation types."""
        # Provide in wrong order to test sorting
        relation_types = [
            _make_mock_relation_type(
                id=2,
                name="竞争",
                name_en="COMPETES_WITH",
                category="商业",
                is_symmetric=True,
                sort_order=2,
                aliases=None,
            ),
            _make_mock_relation_type(
                id=1,
                name="合作",
                name_en="PARTNERS_WITH",
                category="商业",
                is_symmetric=True,
                sort_order=1,
                aliases=None,
            ),
        ]
        # Create a sorted version for mock to return (simulating DB order_by)
        sorted_relation_types = sorted(relation_types, key=lambda rt: rt.sort_order)
        normalizer._pool = _make_mock_pool(sorted_relation_types)

        results = await normalizer.get_all_active()

        assert len(results) == 2
        assert results[0].name == "合作"
        assert results[1].name == "竞争"

    @pytest.mark.asyncio
    async def test_get_all_active_empty(self, normalizer):
        """Test get_all_active() with no relation types."""
        normalizer._pool = _make_mock_pool([])

        results = await normalizer.get_all_active()

        assert results == []

    # ── get_cypher_pattern() tests ───────────────────────────────────────

    def test_get_cypher_pattern_symmetric(self):
        """Test get_cypher_pattern() with symmetric relation."""
        pattern = RelationTypeNormalizer.get_cypher_pattern("PARTNERS_WITH", True)

        assert pattern == "-[r:PARTNERS_WITH]-"

    def test_get_cypher_pattern_asymmetric(self):
        """Test get_cypher_pattern() with asymmetric relation."""
        pattern = RelationTypeNormalizer.get_cypher_pattern("REGULATES", False)

        assert pattern == "-[r:REGULATES]->"

    def test_get_cypher_pattern_various_names(self):
        """Test get_cypher_pattern() with various relation names."""
        symmetric = RelationTypeNormalizer.get_cypher_pattern("INVESTS_IN", True)
        asymmetric = RelationTypeNormalizer.get_cypher_pattern("WORKS_AT", False)

        assert symmetric == "-[r:INVESTS_IN]-"
        assert asymmetric == "-[r:WORKS_AT]->"

    # ── invalidate_cache() tests ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, normalizer):
        """Test invalidate_cache() clears and reloads cache."""
        relation_types = [
            _make_mock_relation_type(
                id=1,
                name="合作",
                name_en="PARTNERS_WITH",
                category="商业",
                is_symmetric=True,
                sort_order=1,
                aliases=None,
            )
        ]
        normalizer._pool = _make_mock_pool(relation_types)

        # First load
        await normalizer._ensure_loaded()
        assert normalizer._loaded is True
        assert len(normalizer._standard_cache) == 1

        # Invalidate
        await normalizer.invalidate_cache()
        assert normalizer._loaded is False
        assert len(normalizer._standard_cache) == 0

    @pytest.mark.asyncio
    async def test_cache_reloads_after_invalidation(self, normalizer):
        """Test cache reloads on next access after invalidation."""
        relation_types = [
            _make_mock_relation_type(
                id=1,
                name="合作",
                name_en="PARTNERS_WITH",
                category="商业",
                is_symmetric=True,
                sort_order=1,
                aliases=None,
            )
        ]
        normalizer._pool = _make_mock_pool(relation_types)

        # Load, invalidate, then use normalize which triggers reload
        await normalizer._ensure_loaded()
        await normalizer.invalidate_cache()

        result = await normalizer.normalize("合作")
        assert result.name_en == "PARTNERS_WITH"
        assert normalizer._loaded is True

    # ── NormalizedRelation dataclass tests ───────────────────────────────

    def test_normalized_relation_is_unknown(self):
        """Test NormalizedRelation.is_unknown property."""
        known = NormalizedRelation(
            raw_type="合作", name="合作", name_en="PARTNERS_WITH", is_symmetric=True
        )
        assert known.is_unknown is False

        unknown = NormalizedRelation(raw_type="未知关系")
        assert unknown.is_unknown is True

    def test_normalized_relation_with_description(self):
        """Test NormalizedRelation with description."""
        relation = NormalizedRelation(
            raw_type="合作",
            name="合作",
            name_en="PARTNERS_WITH",
            is_symmetric=True,
            description="商业合作关系",
        )
        assert relation.description == "商业合作关系"
        assert relation.is_unknown is False

    # ── Suffix cleaning edge cases ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_normalize_multiple_suffixes(self, normalizer):
        """Test normalize() removes only one suffix."""
        relation_types = [
            _make_mock_relation_type(
                id=1,
                name="合作",
                name_en="PARTNERS_WITH",
                category="商业",
                is_symmetric=True,
                sort_order=1,
                aliases=["合作"],
            )
        ]
        normalizer._pool = _make_mock_pool(relation_types)

        # "合作了了" should strip one "了" to "合作了", then "合作"
        result = await normalizer.normalize("合作了了")
        assert result.name_en == "PARTNERS_WITH"

    @pytest.mark.asyncio
    async def test_normalize_suffix_order(self, normalizer):
        """Test normalize() tries suffixes in defined order."""
        relation_types = [
            _make_mock_relation_type(
                id=1,
                name="合作",
                name_en="PARTNERS_WITH",
                category="商业",
                is_symmetric=True,
                sort_order=1,
                aliases=["合作关"],  # Strip "系" to match
            )
        ]
        normalizer._pool = _make_mock_pool(relation_types)

        # "合作关系" should strip "系" to get "合作关"
        result = await normalizer.normalize("合作关系")
        assert result.name_en == "PARTNERS_WITH"

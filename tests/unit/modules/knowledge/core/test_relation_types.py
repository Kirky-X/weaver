# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for RelationTypeNormalizer (knowledge module)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.core.relation_types import NormalizedRelation, RelationTypeNormalizer


def _make_mock_pool() -> AsyncMock:
    """Create a mock PostgresPool with a working session context manager."""
    pool = AsyncMock()
    session = AsyncMock()

    # Make session.execute return a proper mock result
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=result_mock)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.session = MagicMock(return_value=ctx)
    return pool


def _make_mock_relation_type(
    name: str,
    name_en: str,
    is_symmetric: bool = False,
    aliases: list[str] | None = None,
    description: str = "",
    sort_order: int = 0,
) -> MagicMock:
    """Create a mock RelationType ORM object."""
    rt = MagicMock()
    rt.name = name
    rt.name_en = name_en
    rt.is_symmetric = is_symmetric
    rt.description = description
    rt.sort_order = sort_order

    alias_objects = []
    for alias in aliases or []:
        a = MagicMock()
        a.alias = alias
        alias_objects.append(a)
    rt.aliases = alias_objects
    return rt


class TestNormalizedRelation:
    """Tests for NormalizedRelation dataclass."""

    def test_is_unknown_when_name_en_none(self) -> None:
        assert NormalizedRelation(raw_type="test").is_unknown is True

    def test_is_not_unknown_when_name_en_set(self) -> None:
        r = NormalizedRelation(raw_type="test", name_en="TEST")
        assert r.is_unknown is False


class TestRelationTypeNormalizerInit:
    """Tests for initialization."""

    def test_init(self) -> None:
        pool = _make_mock_pool()
        normalizer = RelationTypeNormalizer(pool)
        assert normalizer._loaded is False
        assert normalizer._alias_cache == {}


class TestGetCypherPattern:
    """Tests for get_cypher_pattern static method."""

    def test_symmetric(self) -> None:
        result = RelationTypeNormalizer.get_cypher_pattern("PARTNERS_WITH", True)
        assert result == "-[r:PARTNERS_WITH]-"

    def test_asymmetric(self) -> None:
        result = RelationTypeNormalizer.get_cypher_pattern("REGULATES", False)
        assert result == "-[r:REGULATES]->"


class TestInvalidateCache:
    """Tests for invalidate_cache."""

    @pytest.mark.asyncio
    async def test_invalidate_clears_caches(self) -> None:
        pool = _make_mock_pool()
        normalizer = RelationTypeNormalizer(pool)
        normalizer._loaded = True
        normalizer._alias_cache = {"test": MagicMock()}

        await normalizer.invalidate_cache()

        assert normalizer._loaded is False
        assert normalizer._alias_cache == {}


class TestNormalize:
    """Tests for normalize method."""

    @pytest.mark.asyncio
    async def test_empty_raw_type(self) -> None:
        pool = _make_mock_pool()
        normalizer = RelationTypeNormalizer(pool)
        result = await normalizer.normalize("")
        assert result.is_unknown is True
        assert result.raw_type == ""

    @pytest.mark.asyncio
    async def test_exact_alias_match(self) -> None:
        pool = _make_mock_pool()
        normalizer = RelationTypeNormalizer(pool)
        # Pre-populate cache
        mock_rt = _make_mock_relation_type("合作", "PARTNERS_WITH", True, ["协作", "联合"])
        normalizer._loaded = True
        normalizer._alias_cache = {
            "合作": NormalizedRelation(
                raw_type="合作", name="合作", name_en="PARTNERS_WITH", is_symmetric=True
            ),
            "PARTNERS_WITH": NormalizedRelation(
                raw_type="合作", name="合作", name_en="PARTNERS_WITH", is_symmetric=True
            ),
            "协作": NormalizedRelation(
                raw_type="合作", name="合作", name_en="PARTNERS_WITH", is_symmetric=True
            ),
        }
        normalizer._standard_cache = {
            "合作": NormalizedRelation(
                raw_type="合作", name="合作", name_en="PARTNERS_WITH", is_symmetric=True
            ),
        }
        normalizer._name_en_cache = {
            "PARTNERS_WITH": NormalizedRelation(
                raw_type="合作", name="合作", name_en="PARTNERS_WITH", is_symmetric=True
            ),
        }

        result = await normalizer.normalize("协作")
        assert result.name_en == "PARTNERS_WITH"
        assert result.is_unknown is False

    @pytest.mark.asyncio
    async def test_suffix_cleaning(self) -> None:
        pool = _make_mock_pool()
        normalizer = RelationTypeNormalizer(pool)
        normalizer._loaded = True

        cached = NormalizedRelation(
            raw_type="合作", name="合作", name_en="PARTNERS_WITH", is_symmetric=True
        )
        normalizer._alias_cache = {
            "合作": cached,
        }
        normalizer._standard_cache = {}
        normalizer._name_en_cache = {}

        # "合作了" should clean suffix "了" and match "合作"
        result = await normalizer.normalize("合作了")
        assert result.name_en == "PARTNERS_WITH"

    @pytest.mark.asyncio
    async def test_upper_english_match(self) -> None:
        pool = _make_mock_pool()
        normalizer = RelationTypeNormalizer(pool)
        normalizer._loaded = True

        cached = NormalizedRelation(
            raw_type="合作", name="合作", name_en="PARTNERS_WITH", is_symmetric=True
        )
        normalizer._alias_cache = {}
        normalizer._standard_cache = {}
        normalizer._name_en_cache = {"PARTNERS_WITH": cached}

        result = await normalizer.normalize("partners_with")
        assert result.name_en == "PARTNERS_WITH"

    @pytest.mark.asyncio
    async def test_unknown_type(self) -> None:
        pool = _make_mock_pool()
        normalizer = RelationTypeNormalizer(pool)
        normalizer._loaded = True
        normalizer._alias_cache = {}
        normalizer._standard_cache = {}
        normalizer._name_en_cache = {}

        result = await normalizer.normalize("未知关系类型")
        assert result.is_unknown is True


class TestEnsureLoaded:
    """Tests for _ensure_loaded."""

    @pytest.mark.asyncio
    async def test_skips_if_loaded(self) -> None:
        pool = _make_mock_pool()
        normalizer = RelationTypeNormalizer(pool)
        normalizer._loaded = True

        await normalizer._ensure_loaded()
        pool.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_loads_from_db(self) -> None:
        pool = AsyncMock()
        session = AsyncMock()

        mock_rt = _make_mock_relation_type("合作", "PARTNERS_WITH", True, ["协作"])
        scalars = MagicMock()
        scalars.all.return_value = [mock_rt]
        result = MagicMock()
        result.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=result)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool.session = MagicMock(return_value=ctx)

        normalizer = RelationTypeNormalizer(pool)
        await normalizer._ensure_loaded()

        assert normalizer._loaded is True
        assert "合作" in normalizer._alias_cache
        assert "PARTNERS_WITH" in normalizer._alias_cache
        assert "协作" in normalizer._alias_cache

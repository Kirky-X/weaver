# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Relation type normalizer for knowledge graph relationships.

Provides normalization of LLM-extracted relation types to standard
relation types with aliases, unknown type recording, and Cypher pattern
generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, update

from core.db.models import RelationType, UnknownRelationType
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger("relation_type_normalizer")


@dataclass
class NormalizedRelation:
    """归一化后的关系类型结果

    Attributes:
        raw_type: LLM 原始输出
        name: 标准中文名 (如 "合作")
        name_en: 标准英文名 (如 "PARTNERS_WITH")
        is_symmetric: 是否对称关系
        description: 关系类型描述
    """

    raw_type: str
    name: str | None = None
    name_en: str | None = None
    is_symmetric: bool = False
    description: str | None = None

    @property
    def is_unknown(self) -> bool:
        """Check if this relation type is unknown (not in database)."""
        return self.name_en is None


class RelationTypeNormalizer:
    """关系类型归一化器

    将 LLM 提取的原始关系类型归一化为标准关系类型。
    支持别名匹配、后缀清洗、未知类型记录等功能。

    Implements: NormalizerStrategy

    Args:
        pool: Relational database connection pool.
    """

    def __init__(self, pool: RelationalPool) -> None:
        """Initialize the relation type normalizer.

        Args:
            pool: Relational database connection pool.
        """
        self._pool = pool
        self._alias_cache: dict[str, NormalizedRelation] = {}
        self._standard_cache: dict[str, NormalizedRelation] = {}
        self._name_en_cache: dict[str, NormalizedRelation] = {}
        self._suffixes = ("了", "关系", "于", "中", "的")
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        """从数据库加载缓存。

        查询所有 is_active=True 的 RelationType 及其 aliases，
        填充三个缓存字典。
        """
        if self._loaded:
            return

        async with self._pool.session() as session:
            # 查询所有活跃的关系类型及其别名
            result = await session.execute(
                select(RelationType)
                .where(RelationType.is_active == True)  # noqa: E712
                .order_by(RelationType.sort_order)
            )
            relation_types = result.scalars().all()

            # 清空缓存
            self._alias_cache.clear()
            self._standard_cache.clear()
            self._name_en_cache.clear()

            for rt in relation_types:
                # 创建 NormalizedRelation
                normalized = NormalizedRelation(
                    raw_type=rt.name,
                    name=rt.name,
                    name_en=rt.name_en,
                    is_symmetric=rt.is_symmetric,
                    description=rt.description,
                )

                # 填充标准名缓存
                self._standard_cache[rt.name] = normalized
                self._name_en_cache[rt.name_en] = normalized

                # Fill alias cache (including standard names themselves)
                self._alias_cache[rt.name] = normalized
                self._alias_cache[rt.name_en] = normalized

                # Fill all aliases
                for alias_obj in rt.aliases:
                    self._alias_cache[alias_obj.alias] = normalized

        self._loaded = True
        log.info(
            "relation_type_cache_loaded",
            standard_count=len(self._standard_cache),
            alias_count=len(self._alias_cache),
        )

    async def normalize(self, raw_type: str) -> NormalizedRelation:
        """归一化原始关系类型。

        三步匹配策略：
        1. 精确别名匹配
        2. 后缀清洗匹配
        3. 标准名直接匹配

        Args:
            raw_type: LLM 原始输出的关系类型。

        Returns:
            NormalizedRelation 对象。如果未匹配到，返回 is_unknown=True 的对象。
        """
        await self._ensure_loaded()

        if not raw_type:
            return NormalizedRelation(raw_type="")

        # Step 1: 精确别名匹配
        if raw_type in self._alias_cache:
            cached = self._alias_cache[raw_type]
            return NormalizedRelation(
                raw_type=raw_type,
                name=cached.name,
                name_en=cached.name_en,
                is_symmetric=cached.is_symmetric,
                description=cached.description,
            )

        # Step 2: Suffix cleaning (supports multiple passes, max 3)
        cleaned = raw_type
        for _ in range(3):
            original_cleaned = cleaned
            for suffix in self._suffixes:
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
                    break

            if cleaned in self._alias_cache:
                cached = self._alias_cache[cleaned]
                log.debug("normalize_suffix_cleaned", raw=raw_type, cleaned=cleaned)
                return NormalizedRelation(
                    raw_type=raw_type,
                    name=cached.name,
                    name_en=cached.name_en,
                    is_symmetric=cached.is_symmetric,
                    description=cached.description,
                )

            # Stop loop if no change
            if cleaned == original_cleaned:
                break

        # Step 3: 标准名直接匹配
        if raw_type in self._standard_cache:
            cached = self._standard_cache[raw_type]
            return NormalizedRelation(
                raw_type=raw_type,
                name=cached.name,
                name_en=cached.name_en,
                is_symmetric=cached.is_symmetric,
                description=cached.description,
            )

        # 大写英文名匹配
        upper_raw = raw_type.upper()
        if upper_raw in self._name_en_cache:
            cached = self._name_en_cache[upper_raw]
            return NormalizedRelation(
                raw_type=raw_type,
                name=cached.name,
                name_en=cached.name_en,
                is_symmetric=cached.is_symmetric,
                description=cached.description,
            )

        # No match: return unknown type
        log.debug("normalize_unknown", raw_type=raw_type)
        return NormalizedRelation(raw_type=raw_type)

    async def record_unknown(
        self,
        raw_type: str,
        context: str | None = None,
        article_id: str | UUID | None = None,
    ) -> None:
        """记录未知关系类型。

        如果 raw_type 在 unknown_relation_types 表中已存在且 resolved=False，
        则更新 hit_count 和 last_seen_at。
        否则插入新记录。

        Args:
            raw_type: 未归一化的原始关系类型。
            context: 可选的上下文信息。
            article_id: 可选的文章 ID。
        """
        if not raw_type:
            return

        # 转换 UUID
        if isinstance(article_id, str):
            try:
                article_id = UUID(article_id)
            except ValueError:
                article_id = None

        async with self._pool.session() as session:
            # 查找已存在的未解决记录
            result = await session.execute(
                select(UnknownRelationType).where(
                    UnknownRelationType.raw_type == raw_type,
                    UnknownRelationType.resolved == False,  # noqa: E712
                )
            )
            existing = result.scalar_one_or_none()

            now = datetime.now(UTC)

            if existing:
                # 更新现有记录
                await session.execute(
                    update(UnknownRelationType)
                    .where(UnknownRelationType.id == existing.id)
                    .values(
                        hit_count=existing.hit_count + 1,
                        last_seen_at=now,
                        context=context,
                        article_id=article_id,
                    )
                )
                log.debug(
                    "record_unknown_updated",
                    raw_type=raw_type,
                    hit_count=existing.hit_count + 1,
                )
            else:
                # 插入新记录
                unknown = UnknownRelationType(
                    raw_type=raw_type,
                    context=context,
                    article_id=article_id,
                    hit_count=1,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                session.add(unknown)
                log.debug("record_unknown_inserted", raw_type=raw_type)

            await session.commit()

    async def get_all_active(self) -> list[NormalizedRelation]:
        """获取所有活跃的关系类型。

        Returns:
            按 sort_order 排序的 NormalizedRelation 列表。
        """
        await self._ensure_loaded()

        # 从缓存中获取并按 sort_order 排序
        async with self._pool.session() as session:
            result = await session.execute(
                select(RelationType)
                .where(RelationType.is_active == True)  # noqa: E712
                .order_by(RelationType.sort_order)
            )
            relation_types = result.scalars().all()

            return [
                NormalizedRelation(
                    raw_type=rt.name,
                    name=rt.name,
                    name_en=rt.name_en,
                    is_symmetric=rt.is_symmetric,
                    description=rt.description,
                )
                for rt in relation_types
            ]

    @staticmethod
    def get_cypher_pattern(name_en: str, is_symmetric: bool) -> str:
        """生成 Cypher 关系匹配模式。

        Args:
            name_en: 关系类型英文名。
            is_symmetric: 是否对称关系。

        Returns:
            Cypher 匹配模式字符串。

        Examples:
            >>> get_cypher_pattern("PARTNERS_WITH", True)
            '-[r:PARTNERS_WITH]-'
            >>> get_cypher_pattern("REGULATES", False)
            '-[r:REGULATES]->'
        """
        if is_symmetric:
            return f"-[r:{name_en}]-"
        else:
            return f"-[r:{name_en}]->"

    async def invalidate_cache(self) -> None:
        """清除缓存，强制重新加载。

        用于关系类型更新后刷新缓存。
        """
        self._loaded = False
        self._alias_cache.clear()
        self._standard_cache.clear()
        self._name_en_cache.clear()
        log.info("relation_type_cache_invalidated")

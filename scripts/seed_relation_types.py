#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Seed script for relation types and their aliases.

This script is idempotent - it can be run multiple times safely.
Existing relation types with the same name_en will be skipped.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select

from core.db.models import RelationType, RelationTypeAlias
from core.db.postgres import PostgresPool

# Standard relation types (17 total)
RELATION_TYPES = [
    # sort_order, name, name_en, category, is_symmetric
    (1, "任职于", "WORKS_AT", "组织", False),
    (2, "隶属于", "AFFILIATED_WITH", "组织", False),
    (3, "控股", "CONTROLS", "组织", False),
    (4, "位于", "LOCATED_IN", "空间", False),
    (5, "收购", "ACQUIRES", "商业", False),
    (6, "供应", "SUPPLIES", "商业", False),
    (7, "投资", "INVESTS_IN", "商业", False),
    (8, "合作", "PARTNERS_WITH", "商业", True),
    (9, "竞争", "COMPETES_WITH", "商业", True),
    (10, "发布", "PUBLISHES", "行为", False),
    (11, "签署", "SIGNS", "行为", False),
    (12, "参与", "PARTICIPATES_IN", "行为", False),
    (13, "监管", "REGULATES", "权力", False),
    (14, "支持", "SUPPORTS", "权力", False),
    (15, "制裁", "SANCTIONS", "权力", False),
    (16, "引发", "CAUSES", "因果", False),
    (17, "影响", "INFLUENCES", "因果", False),
]

# Alias mappings: alias -> (name_en, optional description)
ALIASES = [
    # 合作
    ("战略合作", "PARTNERS_WITH"),
    ("战略伙伴", "PARTNERS_WITH"),
    ("联合", "PARTNERS_WITH"),
    ("协作", "PARTNERS_WITH"),
    # 隶属于
    ("归属于", "AFFILIATED_WITH"),
    # 位于
    ("坐落于", "LOCATED_IN"),
    # 投资
    ("投资了", "INVESTS_IN"),
    ("投资于", "INVESTS_IN"),
    # 竞争
    ("竞争关系", "COMPETES_WITH"),
    ("对抗", "COMPETES_WITH"),
    # 监管
    ("管辖", "REGULATES"),
    # 发布
    ("颁布", "PUBLISHES"),
    ("出台", "PUBLISHES"),
    # 控股
    ("持股", "CONTROLS"),
    # 收购
    ("并购", "ACQUIRES"),
    # 任职
    ("就职于", "WORKS_AT"),
    # 供应
    ("提供物资", "SUPPLIES"),
    # 签署
    ("签订", "SIGNS"),
    # 参与
    ("加入", "PARTICIPATES_IN"),
    # 引发
    ("导致", "CAUSES"),
    ("促成", "CAUSES"),
    # 影响
    ("波及", "INFLUENCES"),
    # 制裁
    ("惩罚", "SANCTIONS"),
    # 支持
    ("赞助", "SUPPORTS"),
]


async def seed_relation_types(pool: PostgresPool) -> None:
    """Seed relation types and their aliases.

    Args:
        pool: PostgreSQL connection pool.
    """
    async with pool.session() as session:
        # Build name_en to id mapping for existing relation types
        result = await session.execute(select(RelationType.id, RelationType.name_en))
        existing_map = {row.name_en: row.id for row in result}

        # Insert or skip relation types
        for sort_order, name, name_en, category, is_symmetric in RELATION_TYPES:
            if name_en in existing_map:
                print(f"  Skipping existing relation type: {name} ({name_en})")
                continue

            relation_type = RelationType(
                name=name,
                name_en=name_en,
                category=category,
                is_symmetric=is_symmetric,
                sort_order=sort_order,
            )
            session.add(relation_type)
            print(f"  Adding relation type: {name} ({name_en})")

        await session.commit()

        # Refresh to get IDs for newly inserted relation types
        result = await session.execute(select(RelationType))
        all_relation_types = {rt.name_en: rt for rt in result.scalars()}

        # Build existing alias mapping
        result = await session.execute(
            select(RelationTypeAlias.alias, RelationTypeAlias.relation_type_id)
        )
        existing_aliases = {(row.alias, row.relation_type_id) for row in result}

        # Insert aliases
        for alias, name_en in ALIASES:
            relation_type = all_relation_types.get(name_en)
            if not relation_type:
                print(f"  Warning: Relation type {name_en} not found for alias {alias}")
                continue

            key = (alias, relation_type.id)
            if key in existing_aliases:
                print(f"  Skipping existing alias: {alias} -> {name_en}")
                continue

            alias_record = RelationTypeAlias(alias=alias, relation_type_id=relation_type.id)
            session.add(alias_record)
            print(f"  Adding alias: {alias} -> {name_en}")

        await session.commit()


async def main() -> None:
    """Main entry point."""
    # Use environment variable or default DSN
    import os

    dsn = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver",
    )

    pool = PostgresPool(dsn=dsn)
    await pool.startup()

    try:
        print("Seeding relation types...")
        await seed_relation_types(pool)
        print("Done!")
    finally:
        await pool.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Seed relation types and aliases into the database.

Populates the `relation_types` and `relation_type_aliases` tables with
17 standard relation types across 6 categories, plus common alias mappings
for LLM output normalization.

Usage:
    uv run scripts/seed_relation_types.py          # insert missing types
    uv run scripts/seed_relation_types.py --reset   # delete all and re-insert
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── Seed data ────────────────────────────────────────────────────────────────

RELATION_TYPES: list[dict] = [
    # --- 组织 ---
    {
        "name": "任职于",
        "name_en": "WORKS_AT",
        "category": "组织",
        "is_symmetric": False,
        "sort_order": 1,
        "description": "某人在某组织担任职务",
        "aliases": ["就职于", "工作于", "供职于", "担任", "就职"],
    },
    {
        "name": "隶属于",
        "name_en": "AFFILIATED_WITH",
        "category": "组织",
        "is_symmetric": False,
        "sort_order": 2,
        "description": "某组织隶属于另一组织",
        "aliases": ["隶属", "下属", "从属", "归属", "所属"],
    },
    {
        "name": "控股",
        "name_en": "CONTROLS",
        "category": "组织",
        "is_symmetric": False,
        "sort_order": 3,
        "description": "某组织控股另一组织",
        "aliases": ["控制", "控股关系", "持股", "持有", "掌控", "实际控制"],
    },
    # --- 空间 ---
    {
        "name": "位于",
        "name_en": "LOCATED_IN",
        "category": "空间",
        "is_symmetric": False,
        "sort_order": 4,
        "description": "某实体位于某地理位置",
        "aliases": ["地处", "坐落于", "在", "驻地", "所在地"],
    },
    # --- 商业 ---
    {
        "name": "收购",
        "name_en": "ACQUIRES",
        "category": "商业",
        "is_symmetric": False,
        "sort_order": 5,
        "description": "某实体收购另一实体",
        "aliases": ["并购", "收购了", "吞并", "买下", "收购案"],
    },
    {
        "name": "供应",
        "name_en": "SUPPLIES",
        "category": "商业",
        "is_symmetric": False,
        "sort_order": 6,
        "description": "某实体向另一实体提供产品或服务",
        "aliases": ["提供", "供应商", "供货", "供给", "供应了"],
    },
    {
        "name": "投资",
        "name_en": "INVESTS_IN",
        "category": "商业",
        "is_symmetric": False,
        "sort_order": 7,
        "description": "某实体投资另一实体",
        "aliases": ["注资", "投资了", "融资", "领投", "参投", "入股"],
    },
    {
        "name": "合作",
        "name_en": "PARTNERS_WITH",
        "category": "商业",
        "is_symmetric": True,
        "sort_order": 8,
        "description": "实体之间的合作关系",
        "aliases": ["战略合作", "联合", "合作开发", "协作", "携手", "结盟", "联名"],
    },
    {
        "name": "竞争",
        "name_en": "COMPETES_WITH",
        "category": "商业",
        "is_symmetric": True,
        "sort_order": 9,
        "description": "实体之间的竞争关系",
        "aliases": ["对抗", "竞品", "竞争关系", "对手", "对峙", "相争"],
    },
    # --- 行为 ---
    {
        "name": "发布",
        "name_en": "PUBLISHES",
        "category": "行为",
        "is_symmetric": False,
        "sort_order": 10,
        "description": "某实体发布某内容或产品",
        "aliases": ["公布", "宣布", "发表", "推出", "公布于", "对外发布"],
    },
    {
        "name": "签署",
        "name_en": "SIGNS",
        "category": "行为",
        "is_symmetric": False,
        "sort_order": 11,
        "description": "某实体签署某协议或文件",
        "aliases": ["签订", "签约", "缔结", "达成", "签署了", "签订协议"],
    },
    {
        "name": "参与",
        "name_en": "PARTICIPATES_IN",
        "category": "行为",
        "is_symmetric": False,
        "sort_order": 12,
        "description": "某实体参与某事件或活动",
        "aliases": ["加入", "参加了", "介入", "出席", "参与活动"],
    },
    # --- 权力 ---
    {
        "name": "监管",
        "name_en": "REGULATES",
        "category": "权力",
        "is_symmetric": False,
        "sort_order": 13,
        "description": "某实体监管另一实体",
        "aliases": ["监管关系", "监督", "管理", "管辖", "监察", "督导"],
    },
    {
        "name": "支持",
        "name_en": "SUPPORTS",
        "category": "权力",
        "is_symmetric": False,
        "sort_order": 14,
        "description": "某实体支持另一实体",
        "aliases": ["援助", "资助", "扶持", "力挺", "背书", "支持了"],
    },
    {
        "name": "制裁",
        "name_en": "SANCTIONS",
        "category": "权力",
        "is_symmetric": False,
        "sort_order": 15,
        "description": "某实体对另一实体实施制裁",
        "aliases": ["惩罚", "封禁", "处罚", "禁运", "制裁了", "限制"],
    },
    # --- 因果 ---
    {
        "name": "引发",
        "name_en": "CAUSES",
        "category": "因果",
        "is_symmetric": False,
        "sort_order": 16,
        "description": "某事件引发另一事件",
        "aliases": ["导致", "触发", "造成", "引起", "引发了", "催生"],
    },
    {
        "name": "影响",
        "name_en": "INFLUENCES",
        "category": "因果",
        "is_symmetric": False,
        "sort_order": 17,
        "description": "某实体影响另一实体",
        "aliases": ["左右", "波及", "影响了", "作用于", "传导"],
    },
]


async def seed(reset: bool = False) -> None:
    """Insert relation types and aliases into the database.

    Args:
        reset: If True, delete all existing types and re-insert.
    """
    from sqlalchemy import delete, func, select

    from config.settings import Settings
    from core.db.models import RelationType, RelationTypeAlias
    from core.db.postgres import PostgresPool

    settings = Settings()
    pool = PostgresPool(settings.postgres.dsn)
    await pool.startup()

    async with pool.session() as session:
        if reset:
            await session.execute(delete(RelationTypeAlias))
            await session.execute(delete(RelationType))
            await session.flush()
            print("已清除所有关系类型数据")

        # Count existing
        existing_count = await session.scalar(select(func.count()).select_from(RelationType))
        print(f"数据库中已有 {existing_count} 种关系类型")

        inserted_types = 0
        skipped_types = 0
        inserted_aliases = 0

        for rt_data in RELATION_TYPES:
            aliases = rt_data.pop("aliases")

            # Check if type already exists (by name_en)
            existing = await session.scalar(
                select(RelationType).where(RelationType.name_en == rt_data["name_en"])
            )

            if existing:
                skipped_types += 1
                type_id = existing.id
                print(f"  跳过(已存在): {rt_data['name']} ({rt_data['name_en']})")
            else:
                rt = RelationType(**rt_data, is_active=True)
                session.add(rt)
                await session.flush()
                type_id = rt.id
                inserted_types += 1
                print(f"  插入: {rt_data['name']} ({rt_data['name_en']})")

            # Insert missing aliases
            for alias_str in aliases:
                existing_alias = await session.scalar(
                    select(RelationTypeAlias).where(
                        RelationTypeAlias.relation_type_id == type_id,
                        RelationTypeAlias.alias == alias_str,
                    )
                )
                if not existing_alias:
                    session.add(RelationTypeAlias(alias=alias_str, relation_type_id=type_id))
                    inserted_aliases += 1

        await session.commit()

    print(
        f"\n完成: 插入 {inserted_types} 种类型, 跳过 {skipped_types} 种, 插入 {inserted_aliases} 个别名"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed relation types into the database")
    parser.add_argument("--reset", action="store_true", help="Delete all types and re-insert")
    args = parser.parse_args()
    asyncio.run(seed(reset=args.reset))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""
Unified Management Script

Combines environment validation and database seeding functionality.

Usage:
    python scripts/manage.py validate
    python scripts/manage.py validate --service postgres --service redis
    python scripts/manage.py seed
    python scripts/manage.py seed --reset
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ── Seed Data ────────────────────────────────────────────────────────────────

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


# ── Validate Subcommand ───────────────────────────────────────────────────────


async def run_validate(services: list[str] | None) -> int:
    """Run environment validation using EnvironmentValidator module.

    Args:
        services: Optional list of specific services to validate.

    Returns:
        Exit code (0 for success, 1 for any failures).
    """
    from config.settings import Settings
    from core.health.env_validator import EnvironmentValidator

    try:
        settings = Settings()
    except Exception as exc:
        print(f"\033[91mFailed to load settings:\033[0m {exc}")
        return 1

    validator = EnvironmentValidator(settings)
    results = await validator.validate_all(services)
    validator.print_report(results)

    return validator.get_exit_code(results)


# ── Seed Subcommand ────────────────────────────────────────────────────────────


async def run_seed(reset: bool = False) -> int:
    """Seed relation types and aliases into the database.

    Args:
        reset: If True, delete all existing types and re-insert.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    from sqlalchemy import delete, func, select

    from config.settings import Settings
    from core.db.models import RelationType, RelationTypeAlias
    from core.db.postgres import PostgresPool

    try:
        settings = Settings()
    except Exception as exc:
        print(f"\033[91mFailed to load settings:\033[0m {exc}")
        return 1

    pool = PostgresPool(settings.postgres.dsn)

    try:
        await pool.startup()

        async with pool.session() as session:
            if reset:
                await session.execute(delete(RelationTypeAlias))
                await session.execute(delete(RelationType))
                await session.flush()
                print("Cleared all relation types data")

            # Count existing
            existing_count = await session.scalar(select(func.count()).select_from(RelationType))
            print(f"Existing relation types in database: {existing_count}")

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
                    print(f"  Skipped (exists): {rt_data['name']} ({rt_data['name_en']})")
                else:
                    rt = RelationType(**rt_data, is_active=True)
                    session.add(rt)
                    await session.flush()
                    type_id = rt.id
                    inserted_types += 1
                    print(f"  Inserted: {rt_data['name']} ({rt_data['name_en']})")

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
            f"\nDone: inserted {inserted_types} types, skipped {skipped_types}, "
            f"inserted {inserted_aliases} aliases"
        )
        return 0

    except Exception as exc:
        print(f"\033[91mSeed failed:\033[0m {exc}")
        import traceback

        traceback.print_exc()
        return 1

    finally:
        await pool.shutdown()


# ── Main Entry Point ───────────────────────────────────────────────────────────


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Unified management script for environment validation and database seeding",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Validate subcommand
    validate_parser = subparsers.add_parser(
        "validate", help="Validate environment services (PostgreSQL, Neo4j, Redis, LLM, Embedding)"
    )
    validate_parser.add_argument(
        "--service",
        action="append",
        choices=["postgres", "neo4j", "redis", "llm", "embedding"],
        help="Service to validate (can be specified multiple times)",
    )

    # Seed subcommand
    seed_parser = subparsers.add_parser(
        "seed", help="Seed relation types and aliases into the database"
    )
    seed_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all existing types and re-insert",
    )

    args = parser.parse_args()

    if args.subcommand == "validate":
        return asyncio.run(run_validate(args.service))
    elif args.subcommand == "seed":
        return asyncio.run(run_seed(args.reset))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

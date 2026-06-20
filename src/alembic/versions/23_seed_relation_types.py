# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Seed relation_types and relation_type_aliases tables.

Revision ID: 23_seed_relation_types
Revises: 22_add_llm_usage_new_fields
Create Date: 2026-06-20

Changes:
- Insert 17 seed relation types into relation_types table (if empty)
- Insert 96 corresponding aliases into relation_type_aliases table
- Mirrors DuckDB seed data defined in src/core/db/duckdb_schema.py
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "23_seed_relation_types"
down_revision: str | None = "22_add_llm_usage_new_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Seed data mirrored from src/core/db/duckdb_schema.py::_RELATION_TYPE_SEEDS
_RELATION_TYPE_SEEDS: list[dict] = [
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


def upgrade() -> None:
    """Seed relation_types and relation_type_aliases if the table is empty."""
    bind = op.get_bind()

    # Idempotency: skip if relation_types already has data
    count = bind.execute(sa.text("SELECT COUNT(*) FROM relation_types")).scalar()
    if count and count > 0:
        return

    insert_rt = sa.text("""
        INSERT INTO relation_types
            (name, name_en, category, is_symmetric, sort_order, description, is_active)
        VALUES
            (:name, :name_en, :category, :is_symmetric, :sort_order, :description, true)
        """)
    select_id = sa.text("SELECT id FROM relation_types WHERE name_en = :name_en")
    insert_alias = sa.text(
        "INSERT INTO relation_type_aliases (relation_type_id, alias) VALUES (:rt_id, :alias)"
    )

    for rt in _RELATION_TYPE_SEEDS:
        rt_copy = rt.copy()
        aliases = rt_copy.pop("aliases")
        bind.execute(insert_rt, rt_copy)

        type_id = bind.execute(select_id, {"name_en": rt_copy["name_en"]}).scalar()
        for alias in aliases:
            bind.execute(insert_alias, {"rt_id": type_id, "alias": alias})


def downgrade() -> None:
    """Remove seeded relation_types and their aliases."""
    bind = op.get_bind()

    seeded_name_ens = [rt["name_en"] for rt in _RELATION_TYPE_SEEDS]

    # Delete aliases for seeded relation types
    bind.execute(
        sa.text("""
            DELETE FROM relation_type_aliases
            WHERE relation_type_id IN (
                SELECT id FROM relation_types WHERE name_en = ANY(:name_ens)
            )
            """),
        {"name_ens": seeded_name_ens},
    )

    # Delete seeded relation types
    bind.execute(
        sa.text("DELETE FROM relation_types WHERE name_en = ANY(:name_ens)"),
        {"name_ens": seeded_name_ens},
    )

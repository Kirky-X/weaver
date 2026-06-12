# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DuckDB schema initialization.

Creates all required tables for the Weaver pipeline.
Uses raw SQL to handle DuckDB-specific types (FLOAT[] for vectors, JSON, etc.).
"""

from __future__ import annotations

from sqlalchemy import text

from core.observability import get_logger

log = get_logger(__name__)

# Schema queries ordered by dependency (no FK in DuckDB, but logical order)
SCHEMA_QUERIES = [
    # ── Sources ────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS source_configs
    (
        id VARCHAR PRIMARY KEY,
        name VARCHAR,
        url VARCHAR,
        source_type VARCHAR,
        enabled BOOLEAN DEFAULT true,
        interval_minutes INTEGER DEFAULT 30,
        per_host_concurrency INTEGER DEFAULT 2,
        credibility DECIMAL(3, 2) DEFAULT 0.50,
        tier INTEGER DEFAULT 2,
        last_crawl_time TIMESTAMP WITH TIME ZONE,
        etag VARCHAR,
        last_modified VARCHAR,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Articles Core (vertical split) ─────────────────────────
    """CREATE TABLE IF NOT EXISTS articles_core
    (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        source_url VARCHAR NOT NULL UNIQUE,
        source_host VARCHAR,
        title VARCHAR,
        category VARCHAR,
        language VARCHAR,
        region VARCHAR,
        score DECIMAL(3, 2),
        sentiment_score DECIMAL(3, 2),
        credibility_score DECIMAL(3, 2),
        persist_status VARCHAR DEFAULT 'pending',
        publish_time TIMESTAMP WITH TIME ZONE,
        merged_into UUID,
        is_merged BOOLEAN DEFAULT false,
        merged_source_ids UUID[],
        content_hash VARCHAR,
        version INTEGER DEFAULT 1,
        document_type VARCHAR DEFAULT 'news',
        doc_metadata JSON DEFAULT '{}',
        task_id UUID,
        processing_stage VARCHAR,
        processing_error VARCHAR,
        retry_count INTEGER DEFAULT 0,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Article Bodies (vertical split) ────────────────────────
    """CREATE TABLE IF NOT EXISTS article_bodies
    (
        article_id UUID PRIMARY KEY,
        body VARCHAR,
        summary VARCHAR
    )""",
    # ── Article Analysis (vertical split) ──────────────────────
    """CREATE TABLE IF NOT EXISTS article_analysis
    (
        article_id UUID PRIMARY KEY,
        is_news BOOLEAN DEFAULT false,
        subjects VARCHAR[],
        key_data VARCHAR[],
        impact VARCHAR,
        has_data BOOLEAN,
        quality_score DECIMAL(3, 2),
        sentiment VARCHAR,
        primary_emotion VARCHAR,
        emotion_targets VARCHAR[],
        source_credibility DECIMAL(3, 2),
        cross_verification DECIMAL(3, 2),
        content_check_score DECIMAL(3, 2),
        credibility_flags VARCHAR[],
        verified_by_sources INTEGER DEFAULT 0,
        data_conflicts JSON DEFAULT '[]',
        event_time TIMESTAMP WITH TIME ZONE,
        image_forensics JSON DEFAULT '[]',
        prompt_versions JSON
    )""",
    # ── Source Authorities ──────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS source_authorities
    (
        id BIGINT DEFAULT nextval('source_authorities_seq') PRIMARY KEY,
        host VARCHAR UNIQUE,
        authority DECIMAL(3, 2) DEFAULT 0.50,
        tier INTEGER DEFAULT 2,
        description VARCHAR,
        needs_review BOOLEAN DEFAULT false,
        auto_score DECIMAL(3, 2),
        manual_score DECIMAL(3, 2),
        final_score DECIMAL(3, 2),
        article_count INTEGER DEFAULT 0,
        last_crawled_at TIMESTAMP WITH TIME ZONE,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Pending Sync ────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS pending_sync
    (
        id BIGINT DEFAULT nextval('pending_sync_seq') PRIMARY KEY,
        article_id UUID,
        sync_type VARCHAR,
        payload JSON,
        status VARCHAR DEFAULT 'pending',
        retry_count INTEGER DEFAULT 0,
        error VARCHAR,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        synced_at TIMESTAMP WITH TIME ZONE
    )""",
    # ── LLM Failure Records ─────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS llm_failure_records
    (
        id BIGINT DEFAULT nextval('llm_failure_records_seq') PRIMARY KEY,
        call_point VARCHAR,
        provider VARCHAR,
        error_type VARCHAR,
        error_detail VARCHAR,
        latency_ms DECIMAL(10, 2),
        article_id UUID,
        task_id VARCHAR,
        attempt INTEGER,
        fallback_tried BOOLEAN DEFAULT false,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── LLM Usage Raw ───────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS llm_usage_raw
    (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        label VARCHAR,
        call_point VARCHAR,
        llm_type VARCHAR,
        provider VARCHAR,
        model VARCHAR,
        input_tokens INTEGER,
        output_tokens INTEGER,
        total_tokens INTEGER,
        latency_ms DECIMAL(10, 2),
        success BOOLEAN DEFAULT true,
        error_type VARCHAR,
        article_id UUID,
        task_id VARCHAR,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── LLM Usage Hourly ────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS llm_usage_hourly
    (
        id BIGINT DEFAULT nextval('llm_usage_hourly_seq') PRIMARY KEY,
        time_bucket TIMESTAMP WITH TIME ZONE NOT NULL,
        label VARCHAR(100) NOT NULL,
        call_point VARCHAR(100) NOT NULL,
        llm_type VARCHAR(20) NOT NULL,
        provider VARCHAR(50) NOT NULL,
        model VARCHAR(100) NOT NULL,
        call_count INTEGER DEFAULT 0,
        input_tokens_sum INTEGER DEFAULT 0,
        output_tokens_sum INTEGER DEFAULT 0,
        total_tokens_sum INTEGER DEFAULT 0,
        latency_avg_ms DOUBLE,
        latency_min_ms DOUBLE,
        latency_max_ms DOUBLE,
        success_count INTEGER DEFAULT 0,
        failure_count INTEGER DEFAULT 0,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        UNIQUE (time_bucket, label, call_point)
    )""",
    # ── Relation Types ──────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS relation_types
    (
        id BIGINT DEFAULT nextval('relation_types_seq') PRIMARY KEY,
        name VARCHAR(50) UNIQUE,
        name_en VARCHAR(50) UNIQUE,
        category VARCHAR(20),
        is_symmetric BOOLEAN DEFAULT false,
        is_active BOOLEAN DEFAULT true,
        description VARCHAR,
        sort_order INTEGER DEFAULT 0,
        usage_count INTEGER DEFAULT 0,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Relation Type Aliases ───────────────────────────────────
    """CREATE TABLE IF NOT EXISTS relation_type_aliases
    (
        id BIGINT DEFAULT nextval('relation_type_aliases_seq') PRIMARY KEY,
        relation_type_id BIGINT,
        alias VARCHAR(100),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Unknown Relation Types ──────────────────────────────────
    """CREATE TABLE IF NOT EXISTS unknown_relation_types
    (
        id BIGINT DEFAULT nextval('unknown_relation_types_seq') PRIMARY KEY,
        raw_type VARCHAR,
        context VARCHAR,
        hit_count INTEGER DEFAULT 1,
        first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Article Vectors ─────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS article_vectors
    (
        article_id VARCHAR,
        vector_type VARCHAR,
        embedding FLOAT[1024],
        model_id VARCHAR NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        PRIMARY KEY (article_id, vector_type)
    )""",
    # ── Entity Vectors ──────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS entity_vectors
    (
        id BIGINT DEFAULT nextval('entity_vectors_seq') PRIMARY KEY,
        neo4j_id VARCHAR UNIQUE,
        embedding FLOAT[1024],
        model_id VARCHAR NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Community Vectors ───────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS community_vectors
    (
        id BIGINT DEFAULT nextval('community_vectors_seq') PRIMARY KEY,
        community_id VARCHAR,
        embedding FLOAT[1024],
        model_id VARCHAR,
        title VARCHAR,
        summary VARCHAR,
        entity_count INTEGER DEFAULT 0,
        article_count INTEGER DEFAULT 0,
        rank DECIMAL(3, 2),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Sentiment Shifts ────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS sentiment_shifts
    (
        id BIGINT DEFAULT nextval('sentiment_shifts_seq') PRIMARY KEY,
        community_id VARCHAR,
        community_title VARCHAR,
        shift_type VARCHAR,
        direction VARCHAR,
        magnitude DECIMAL(5, 4),
        confidence DECIMAL(5, 4),
        detected_at TIMESTAMP WITH TIME ZONE,
        window_start TIMESTAMP WITH TIME ZONE,
        window_end TIMESTAMP WITH TIME ZONE,
        before_avg DECIMAL(5, 4),
        after_avg DECIMAL(5, 4),
        trigger_article_ids VARCHAR[]
    )""",
    # ── Daily Briefings ─────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS daily_briefings
    (
        id BIGINT DEFAULT nextval('daily_briefings_seq') PRIMARY KEY,
        briefing_date DATE,
        title VARCHAR,
        summary VARCHAR,
        status VARCHAR DEFAULT 'draft',
        total_items INTEGER DEFAULT 0,
        generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Daily Briefing Items ────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS daily_briefing_items
    (
        id BIGINT DEFAULT nextval('daily_briefing_items_seq') PRIMARY KEY,
        briefing_id BIGINT,
        article_id UUID,
        rank INTEGER,
        score DECIMAL(5, 3),
        score_breakdown JSON,
        category VARCHAR,
        reason VARCHAR
    )""",
    # ── API Keys ────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS api_keys
    (
        id BIGINT DEFAULT nextval('api_keys_seq') PRIMARY KEY,
        key_id VARCHAR,
        key_hash VARCHAR,
        scopes JSON,
        rate_limit_per_min INTEGER DEFAULT 100,
        expires_at TIMESTAMP WITH TIME ZONE,
        last_used_at TIMESTAMP WITH TIME ZONE,
        is_revoked BOOLEAN DEFAULT false,
        rotated_to VARCHAR,
        created_by VARCHAR,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Alert Rules ─────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS alert_rules
    (
        id BIGINT DEFAULT nextval('alert_rules_seq') PRIMARY KEY,
        entity_name VARCHAR,
        metric VARCHAR,
        operator VARCHAR,
        threshold DECIMAL(10, 2),
        channel VARCHAR DEFAULT 'webhook',
        cooldown_minutes INTEGER DEFAULT 60,
        enabled BOOLEAN DEFAULT true,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Alert Events ────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS alert_events
    (
        id BIGINT DEFAULT nextval('alert_events_seq') PRIMARY KEY,
        rule_id BIGINT,
        entity_name VARCHAR,
        metric_value DECIMAL(10, 2),
        triggered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        acknowledged_at TIMESTAMP WITH TIME ZONE,
        detail JSON
    )""",
    # ── Article Versions ────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS article_versions
    (
        id BIGINT DEFAULT nextval('article_versions_seq') PRIMARY KEY,
        article_id UUID,
        version INTEGER,
        title VARCHAR,
        body VARCHAR,
        summary VARCHAR,
        category VARCHAR,
        score DECIMAL(3, 2),
        changed_fields VARCHAR[],
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        UNIQUE (article_id, version)
    )""",
    # ── Audit Log ───────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS audit_log
    (
        id BIGINT DEFAULT nextval('audit_log_seq') PRIMARY KEY,
        key_id VARCHAR,
        action VARCHAR,
        target_type VARCHAR,
        target_id VARCHAR,
        detail JSON,
        client_ip VARCHAR,
        user_agent VARCHAR,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── LLM Compare Hourly ──────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS llm_compare_hourly
    (
        id BIGINT DEFAULT nextval('llm_compare_hourly_seq') PRIMARY KEY,
        time_bucket TIMESTAMP WITH TIME ZONE,
        call_point VARCHAR,
        primary_model VARCHAR,
        candidate_model VARCHAR,
        comparison_count INTEGER DEFAULT 0,
        primary_latency_sum DOUBLE DEFAULT 0.0,
        candidate_latency_sum DOUBLE DEFAULT 0.0,
        primary_success_count INTEGER DEFAULT 0,
        candidate_success_count INTEGER DEFAULT 0,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        UNIQUE (time_bucket, call_point, primary_model, candidate_model)
    )""",
]

# Sequences for BIGINT PK tables (must be created before tables)
SEQUENCE_QUERIES = [
    "CREATE SEQUENCE IF NOT EXISTS source_authorities_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS pending_sync_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS llm_failure_records_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS llm_usage_hourly_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS entity_vectors_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS relation_types_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS relation_type_aliases_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS unknown_relation_types_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS community_vectors_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS sentiment_shifts_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS daily_briefings_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS daily_briefing_items_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS api_keys_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS alert_rules_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS alert_events_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS article_versions_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS audit_log_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS llm_compare_hourly_seq START 1",
]

# Views for backward compatibility (must be created after tables)
VIEW_QUERIES = [
    """CREATE VIEW IF NOT EXISTS articles AS
    SELECT c.*, b.body, b.summary,
           a.is_news, a.subjects, a.key_data, a.impact, a.has_data,
           a.quality_score, a.sentiment, a.primary_emotion, a.emotion_targets,
           a.source_credibility, a.cross_verification, a.content_check_score,
           a.credibility_flags, a.verified_by_sources, a.data_conflicts,
           a.event_time, a.image_forensics, a.prompt_versions
    FROM articles_core c
    LEFT JOIN article_bodies b ON c.id = b.article_id
    LEFT JOIN article_analysis a ON c.id = a.article_id""",
]


async def initialize_duckdb_schema(pool) -> None:
    """Initialize DuckDB schema with all required tables.

    Args:
        pool: DuckDBPool instance.

    Note:
        Uses a single session for all operations because DuckDB :memory:
        creates a separate database for each connection. All schema operations
        must happen in the same session/connection.
    """
    log.info("duckdb_schema_initializing")

    # Use single session for all operations (DuckDB :memory: isolation)
    session = pool.session()
    try:
        # Create sequences first
        for query in SEQUENCE_QUERIES:
            try:
                await session.execute(text(query))
            except Exception as exc:
                log.warning("duckdb_sequence_create_failed", error=str(exc))

        # Create tables
        for query in SCHEMA_QUERIES:
            try:
                await session.execute(text(query))
            except Exception as exc:
                log.warning("duckdb_table_create_failed", error=str(exc))

        # Create views
        for query in VIEW_QUERIES:
            try:
                await session.execute(text(query))
            except Exception as exc:
                log.warning("duckdb_view_create_failed", error=str(exc))

        # Seed relation types if empty (in same session)
        await _seed_relation_types(session)

        await session.commit()
        log.info("duckdb_schema_initialized")
    except Exception as exc:
        await session.rollback()
        log.error("duckdb_schema_init_failed", error=str(exc))
        raise
    finally:
        await session.close()


# ── Seed Data ────────────────────────────────────────────────────────

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


async def _seed_relation_types(session) -> None:
    """Insert seed relation types if the table is empty.

    Args:
        session: Database session (must be same session used for schema creation).
    """
    result = await session.execute(text("SELECT COUNT(*) FROM relation_types"))
    count = result.scalar()

    if count > 0:
        log.debug("relation_types_already_seeded", count=count)
        return

    for rt in _RELATION_TYPE_SEEDS:
        # Make a copy to avoid mutating the original seed data
        rt_copy = rt.copy()
        aliases = rt_copy.pop("aliases")
        await session.execute(
            text("""
                 INSERT INTO relation_types (name, name_en, category, is_symmetric, sort_order, description, is_active)
                 VALUES (:name, :name_en, :category, :is_symmetric, :sort_order, :description, true)
                 """),
            rt_copy,
        )
        # Get the inserted id
        result = await session.execute(
            text("SELECT id FROM relation_types WHERE name_en = :name_en"),
            {"name_en": rt_copy["name_en"]},
        )
        type_id = result.scalar()

        for alias in aliases:
            await session.execute(
                text(
                    "INSERT INTO relation_type_aliases (relation_type_id, alias) VALUES (:rt_id, :alias)"
                ),
                {"rt_id": type_id, "alias": alias},
            )

    log.info("relation_types_seeded", count=len(_RELATION_TYPE_SEEDS))

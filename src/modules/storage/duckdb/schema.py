# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DuckDB schema initialization.

Creates all required tables for the Weaver pipeline.
Uses raw SQL to handle DuckDB-specific types (FLOAT[] for vectors, JSON, etc.).
"""

from __future__ import annotations

from core.observability.logging import get_logger

log = get_logger("duckdb_schema")

# Schema queries ordered by dependency (no FK in DuckDB, but logical order)
SCHEMA_QUERIES = [
    # ── Sources ────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS sources (
        id VARCHAR PRIMARY KEY,
        name VARCHAR,
        url VARCHAR,
        source_type VARCHAR,
        enabled BOOLEAN DEFAULT true,
        interval_minutes INTEGER DEFAULT 30,
        per_host_concurrency INTEGER DEFAULT 2,
        credibility DECIMAL(3,2) DEFAULT 0.50,
        tier INTEGER DEFAULT 2,
        last_crawl_time TIMESTAMP WITH TIME ZONE,
        etag VARCHAR,
        last_modified VARCHAR,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Articles ────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS articles (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        source_url VARCHAR NOT NULL,
        source_host VARCHAR,
        is_news BOOLEAN DEFAULT false,
        title VARCHAR,
        body VARCHAR,
        category VARCHAR,
        language VARCHAR,
        region VARCHAR,
        merged_into UUID,
        is_merged BOOLEAN DEFAULT false,
        merged_source_ids UUID[],
        summary VARCHAR,
        event_time TIMESTAMP WITH TIME ZONE,
        subjects VARCHAR[],
        key_data VARCHAR[],
        impact VARCHAR,
        has_data BOOLEAN DEFAULT false,
        score DECIMAL(3,2),
        quality_score DECIMAL(3,2),
        sentiment VARCHAR,
        sentiment_score DECIMAL(3,2),
        primary_emotion VARCHAR,
        emotion_targets VARCHAR[],
        credibility_score DECIMAL(3,2),
        source_credibility DECIMAL(3,2),
        cross_verification DECIMAL(3,2),
        content_check_score DECIMAL(3,2),
        credibility_flags VARCHAR[],
        verified_by_sources INTEGER DEFAULT 0,
        persist_status VARCHAR DEFAULT 'pending',
        task_id UUID,
        processing_stage VARCHAR,
        processing_error VARCHAR,
        retry_count INTEGER DEFAULT 0,
        prompt_versions JSON,
        publish_time TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Article Embeddings ──────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS article_embeddings (
        article_id UUID PRIMARY KEY,
        embedding FLOAT[1024],
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Source Authorities ──────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS source_authorities (
        id BIGINT DEFAULT nextval('source_authorities_seq') PRIMARY KEY,
        host VARCHAR UNIQUE,
        authority DECIMAL(3,2) DEFAULT 0.50,
        tier INTEGER DEFAULT 2,
        description VARCHAR,
        needs_review BOOLEAN DEFAULT false,
        auto_score DECIMAL(3,2),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Pending Sync ────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS pending_sync (
        id BIGINT DEFAULT nextval('pending_sync_seq') PRIMARY KEY,
        article_id UUID,
        sync_type VARCHAR,
        payload JSON,
        status VARCHAR DEFAULT 'pending',
        retry_count INTEGER DEFAULT 0,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── LLM Failures ────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS llm_failures (
        id BIGINT DEFAULT nextval('llm_failures_seq') PRIMARY KEY,
        call_point VARCHAR,
        provider VARCHAR,
        error_type VARCHAR,
        error_detail VARCHAR,
        latency_ms DECIMAL(10,2),
        article_id UUID,
        task_id VARCHAR,
        attempt INTEGER,
        fallback_tried BOOLEAN DEFAULT false,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── LLM Usage Raw ───────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS llm_usage_raw (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        provider VARCHAR,
        model VARCHAR,
        call_point VARCHAR,
        input_tokens INTEGER,
        output_tokens INTEGER,
        latency_ms DECIMAL(10,2),
        success BOOLEAN DEFAULT true,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── LLM Usage Hourly ────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS llm_usage_hourly (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        hour_timestamp TIMESTAMP WITH TIME ZONE,
        provider VARCHAR,
        model VARCHAR,
        call_point VARCHAR,
        request_count INTEGER DEFAULT 0,
        total_input_tokens BIGINT DEFAULT 0,
        total_output_tokens BIGINT DEFAULT 0,
        total_latency_ms DECIMAL(15,2) DEFAULT 0,
        success_count INTEGER DEFAULT 0,
        failure_count INTEGER DEFAULT 0,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Relation Types ──────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS relation_types (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        name VARCHAR,
        description VARCHAR,
        is_active BOOLEAN DEFAULT true,
        usage_count INTEGER DEFAULT 0,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Relation Type Aliases ───────────────────────────────────
    """CREATE TABLE IF NOT EXISTS relation_type_aliases (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        relation_type_id UUID,
        alias VARCHAR,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    # ── Unknown Relation Types ──────────────────────────────────
    """CREATE TABLE IF NOT EXISTS unknown_relation_types (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        name VARCHAR,
        occurrence_count INTEGER DEFAULT 1,
        first_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
]

# Sequences for BIGINT PK tables
SEQUENCE_QUERIES = [
    "CREATE SEQUENCE IF NOT EXISTS source_authorities_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS pending_sync_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS llm_failures_seq START 1",
]


async def initialize_duckdb_schema(pool) -> None:
    """Initialize DuckDB schema with all required tables.

    Args:
        pool: DuckDBPool instance.
    """
    log.info("duckdb_schema_initializing")

    # Create sequences first
    for query in SEQUENCE_QUERIES:
        try:
            async with pool.session_context() as session:
                await session.execute(query)
        except Exception as exc:
            log.debug("duckdb_sequence_check", error=str(exc))

    # Create tables
    for query in SCHEMA_QUERIES:
        try:
            async with pool.session_context() as session:
                await session.execute(query)
        except Exception as exc:
            log.debug("duckdb_table_check", error=str(exc))

    log.info("duckdb_schema_initialized")

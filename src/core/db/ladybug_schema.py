# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""LadybugDB schema initialization.

LadybugDB requires explicit schema definition before data insertion.
Uses CREATE NODE TABLE and CREATE REL TABLE syntax.
"""

from core.observability import get_logger

log = get_logger(__name__)

# Schema queries for LadybugDB
SCHEMA_QUERIES = [
    """
    CREATE NODE TABLE IF NOT EXISTS Entity (
        id STRING PRIMARY KEY,
        canonical_name STRING,
        type STRING,
        aliases STRING[],
        description STRING,
        tier INT64,
        created_at INT64,
        updated_at INT64
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Article (
        id STRING PRIMARY KEY,
        pg_id STRING,
        title STRING,
        category STRING,
        publish_time INT64,
        score DOUBLE
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Community (
        id STRING PRIMARY KEY,
        title STRING,
        summary STRING,
        level INT64,
        parent_id STRING,
        children_ids STRING,
        entity_count INT64,
        article_count INT64,
        rank DOUBLE,
        period STRING,
        modularity DOUBLE,
        created_at INT64,
        updated_at INT64
    )
    """,
    # R3 fix: backfill article_count on pre-existing Community tables.
    # New databases pick up the column from CREATE NODE TABLE above; existing
    # databases need ALTER TABLE. Wrapped in try/except by initialize_ladybug_schema.
    "ALTER TABLE Community ADD COLUMN article_count INT64",
    """
    CREATE NODE TABLE IF NOT EXISTS CommunityReport (
        id STRING PRIMARY KEY,
        community_id STRING,
        title STRING,
        summary STRING,
        full_content STRING,
        key_entities STRING,
        key_relationships STRING,
        rank DOUBLE,
        stale BOOLEAN,
        full_content_embedding FLOAT[1024],
        created_at INT64,
        updated_at INT64
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS EventNode (
        id STRING PRIMARY KEY,
        content STRING,
        attributes STRING,
        event_type STRING,
        name STRING,
        description STRING,
        event_time INT64,
        created_at INT64,
        embedding DOUBLE[]
    )
    """,
    # D2 / Task 6.4: backfill embedding column on pre-existing EventNode tables.
    # New databases pick up the column from CREATE NODE TABLE above; existing
    # databases need ALTER TABLE. Wrapped in try/except by initialize_ladybug_schema
    # so already-migrated databases skip silently. LadybugDB supports DOUBLE[]
    # list properties natively (see Entity.aliases STRING[] above).
    "ALTER TABLE EventNode ADD COLUMN embedding DOUBLE[]",
    """
    CREATE REL TABLE IF NOT EXISTS MENTIONS (
        FROM Article TO Entity,
        role STRING
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS FOLLOWED_BY (
        FROM Article TO Article,
        time_gap_hours DOUBLE
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS EVENT_FOLLOWED_BY (
        FROM EventNode TO EventNode,
        time_gap_hours DOUBLE
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS CAUSES (
        FROM EventNode TO EventNode,
        confidence DOUBLE
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS ENABLES (
        FROM EventNode TO EventNode,
        strength DOUBLE
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS PREVENTS (
        FROM EventNode TO EventNode
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS RELATED_TO (
        FROM Entity TO Entity,
        edge_type STRING,
        properties STRING,
        weight DOUBLE,
        created_at INT64,
        updated_at INT64
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS HAS_ENTITY (
        FROM Community TO Entity
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS REPORTS_ON (
        FROM CommunityReport TO Community
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS NarrativeNode (
        id STRING PRIMARY KEY,
        source_bias STRING,
        frame STRING,
        tone STRING,
        emphasis STRING,
        created_at INT64,
        updated_at INT64
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS SchemaNode (
        id STRING PRIMARY KEY,
        event_type STRING,
        pattern STRING,
        confidence DOUBLE,
        created_at INT64,
        updated_at INT64
    )
    """,
    # _CommunityMetadata node table — singleton node for community detection state
    """
    CREATE NODE TABLE IF NOT EXISTS _CommunityMetadata (
        id STRING PRIMARY KEY,
        last_full_rebuild_at INT64,
        last_incremental_update_at INT64,
        pending_entity_count INT64,
        entity_count INT64,
        modularity DOUBLE
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS HAS_PARTICIPANT (
        FROM EventNode TO Entity,
        role STRING,
        created_at INT64
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS HAS_SUB_EVENT (
        FROM EventNode TO EventNode,
        created_at INT64
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS HAS_NARRATIVE (
        FROM EventNode TO NarrativeNode,
        created_at INT64
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS HAS_EVENT (
        FROM Article TO EventNode
    )
    """,
]


async def initialize_ladybug_schema(pool) -> None:
    """Initialize LadybugDB schema with all node and relationship tables.

    Args:
        pool: LadybugPool instance with execute_query method.
    """
    for query in SCHEMA_QUERIES:
        try:
            await pool.execute_query(query)
            log.info("ladybug_schema_created", query=query[:50])
        except Exception as exc:
            # Table may already exist
            log.debug("ladybug_schema_check", error=str(exc))

    log.info("ladybug_schema_initialized")

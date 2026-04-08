# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB schema initialization.

LadybugDB requires explicit schema definition before data insertion.
Uses CREATE NODE TABLE and CREATE REL TABLE syntax.
"""

from core.observability.logging import get_logger

log = get_logger("ladybug_schema")

# Schema queries for LadybugDB
SCHEMA_QUERIES = [
    # Entity node table
    """
    CREATE NODE TABLE IF NOT EXISTS Entity (
        id STRING PRIMARY KEY,
        canonical_name STRING,
        type STRING,
        description STRING,
        tier INT64,
        created_at INT64,
        updated_at INT64
    )
    """,
    # Article node table
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
    # Community node table
    """
    CREATE NODE TABLE IF NOT EXISTS Community (
        id STRING PRIMARY KEY,
        title STRING,
        summary STRING,
        level INT64,
        rank DOUBLE,
        created_at INT64
    )
    """,
    # CommunityReport node table
    """
    CREATE NODE TABLE IF NOT EXISTS CommunityReport (
        id STRING PRIMARY KEY,
        community_id STRING,
        title STRING,
        summary STRING,
        full_content STRING,
        full_content_embedding FLOAT[1024],
        created_at INT64
    )
    """,
    # EventNode node table
    """
    CREATE NODE TABLE IF NOT EXISTS EventNode (
        id STRING PRIMARY KEY,
        event_type STRING,
        name STRING,
        description STRING,
        event_time INT64,
        created_at INT64
    )
    """,
    # MENTIONS relationship - Article mentions Entity
    """
    CREATE REL TABLE IF NOT EXISTS MENTIONS (
        FROM Article TO Entity,
        role STRING
    )
    """,
    # FOLLOWED_BY relationship - Article followed by Article
    """
    CREATE REL TABLE IF NOT EXISTS FOLLOWED_BY (
        FROM Article TO Article,
        time_gap_hours DOUBLE
    )
    """,
    # RELATED_TO relationship - Entity related to Entity (for dynamic edge types)
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
    # HAS_ENTITY relationship - Community has Entity member
    """
    CREATE REL TABLE IF NOT EXISTS HAS_ENTITY (
        FROM Community TO Entity
    )
    """,
    # REPORTS_ON relationship - CommunityReport reports on Community
    """
    CREATE REL TABLE IF NOT EXISTS REPORTS_ON (
        FROM CommunityReport TO Community
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

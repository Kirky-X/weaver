# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB storage module - embedded graph database.

LadybugDB is a Kuzu fork that provides an embedded graph database
with Cypher query support. Key differences from Neo4j:
- No elementId() function - use id property as string
- No datetime() function - use timestamp integers
- Dynamic relationship types not supported - use RELATED_TO with edge_type property
- UNWIND with parameters may not work - use loops instead
"""

from modules.storage.ladybug.article_repo import LadybugArticleRepo
from modules.storage.ladybug.entity_repo import LadybugEntityRepo
from modules.storage.ladybug.temporal_repo import LadybugTemporalRepo
from modules.storage.ladybug.writer import LadybugWriter

__all__ = [
    "LadybugArticleRepo",
    "LadybugEntityRepo",
    "LadybugTemporalRepo",
    "LadybugWriter",
]

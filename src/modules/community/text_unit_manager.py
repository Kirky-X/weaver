"""Text unit management for fine-grained knowledge graph content.

Text units are smaller text chunks that can be linked to entities,
providing more granular context for search and analysis.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger

log = get_logger("text_unit")


@dataclass
class TextUnit:
    """A text unit linked to entities in the knowledge graph."""

    id: str
    content: str
    source_article_id: str | None
    chunk_index: int
    token_count: int
    entity_ids: list[str] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class TextUnitManager:
    """Manage text units for knowledge graph.

    Text units provide fine-grained text chunks that can be
    linked to entities for more precise context retrieval.
    """

    def __init__(
        self,
        neo4j_pool: Neo4jPool,
        default_chunk_size: int = 500,
        overlap: int = 50,
    ) -> None:
        """Initialize text unit manager.

        Args:
            neo4j_pool: Neo4j connection pool.
            default_chunk_size: Default chunk size in characters.
            overlap: Character overlap between chunks.
        """
        self._pool = neo4j_pool
        self._chunk_size = default_chunk_size
        self._overlap = overlap

    def chunk_text(
        self,
        text: str,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[str]:
        """Split text into overlapping chunks.

        Args:
            text: Text to chunk.
            chunk_size: Size of each chunk.
            overlap: Overlap between chunks.

        Returns:
            List of text chunks.
        """
        chunk_size = chunk_size or self._chunk_size
        overlap = overlap or self._overlap

        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size

            if end < len(text):
                last_period = text.rfind('。', start, end)
                last_newline = text.rfind('\n', start, end)
                cut_point = max(last_period, last_newline)

                if cut_point > start:
                    end = cut_point + 1

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end - overlap

        return chunks

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other = len(text) - chinese
        return chinese + other // 4

    async def create_text_units(
        self,
        article_id: str,
        text: str,
        entity_mapping: dict[str, list[str]] | None = None,
    ) -> list[TextUnit]:
        """Create text units from article text.

        Args:
            article_id: Source article ID.
            text: Article text content.
            entity_mapping: Optional mapping of chunk indices to entity names.

        Returns:
            List of created TextUnits.
        """
        chunks = self.chunk_text(text)
        text_units = []

        for i, chunk in enumerate(chunks):
            unit = TextUnit(
                id=str(uuid.uuid4()),
                content=chunk,
                source_article_id=article_id,
                chunk_index=i,
                token_count=self.estimate_tokens(chunk),
                entity_names=entity_mapping.get(i, []) if entity_mapping else [],
            )
            text_units.append(unit)

        await self._save_text_units(text_units)

        return text_units

    async def _save_text_units(self, units: list[TextUnit]) -> None:
        """Save text units to Neo4j."""
        for unit in units:
            cypher = """
            MERGE (t:TextUnit {id: $id})
            SET t.content = $content,
                t.source_article_id = $source_article_id,
                t.chunk_index = $chunk_index,
                t.token_count = $token_count,
                t.entity_names = $entity_names,
                t.created_at = $created_at
            """

            await self._pool.execute_query(cypher, {
                "id": unit.id,
                "content": unit.content,
                "source_article_id": unit.source_article_id,
                "chunk_index": unit.chunk_index,
                "token_count": unit.token_count,
                "entity_names": unit.entity_names,
                "created_at": unit.created_at.isoformat(),
            })

    async def get_text_unit(self, unit_id: str) -> TextUnit | None:
        """Retrieve a text unit by ID."""
        cypher = """
        MATCH (t:TextUnit {id: $id})
        RETURN t.id AS id,
               t.content AS content,
               t.source_article_id AS source_article_id,
               t.chunk_index AS chunk_index,
               t.token_count AS token_count,
               t.entity_names AS entity_names,
               t.created_at AS created_at
        """

        try:
            results = await self._pool.execute_query(cypher, {"id": unit_id})
            if results:
                r = results[0]
                return TextUnit(
                    id=r["id"],
                    content=r["content"],
                    source_article_id=r.get("source_article_id"),
                    chunk_index=r.get("chunk_index", 0),
                    token_count=r.get("token_count", 0),
                    entity_names=r.get("entity_names", []),
                    created_at=r.get("created_at", datetime.now(timezone.utc)),
                )
        except Exception as exc:
            log.warning("get_text_unit_failed", error=str(exc))

        return None

    async def get_entity_text_units(
        self,
        entity_name: str,
        limit: int = 10,
    ) -> list[TextUnit]:
        """Get text units containing an entity."""
        cypher = """
        MATCH (t:TextUnit)
        WHERE entity_name IN t.entity_names
        OPTIONAL MATCH (e:Entity {canonical_name: entity_name})-[:MENTIONS]-(a:Article)
        WHERE t.source_article_id = a.pg_id
        RETURN t.id AS id,
               t.content AS content,
               t.source_article_id AS source_article_id,
               t.chunk_index AS chunk_index,
               t.token_count AS token_count,
               t.entity_names AS entity_names,
               t.created_at AS created_at
        ORDER BY t.chunk_index
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(cypher, {
                "entity_name": entity_name,
                "limit": limit,
            })
            return [self._row_to_unit(r) for r in results]
        except Exception as exc:
            log.warning("get_entity_text_units_failed", error=str(exc))
            return []

    def _row_to_unit(self, row: dict) -> TextUnit:
        """Convert database row to TextUnit."""
        return TextUnit(
            id=row.get("id", ""),
            content=row.get("content", ""),
            source_article_id=row.get("source_article_id"),
            chunk_index=row.get("chunk_index", 0),
            token_count=row.get("token_count", 0),
            entity_names=row.get("entity_names", []),
            created_at=row.get("created_at", datetime.now(timezone.utc)),
        )

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Knowledge cluster cache storage using DuckDB + Parquet.

Provides in-memory DuckDB storage with async Parquet persistence
for semantic similarity search result caching.

Security Note: SQL queries use f-strings with table_name, but table_name
is an internal constant ("knowledge_clusters"), not user input. S608 warnings
are suppressed as these are false positives.
"""

# trust-verified: table_name is internal constant, not user input
# ruff: noqa: S608

from __future__ import annotations

import atexit
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from core.db.safe_query import validate_sql_identifier
from core.observability import get_logger
from core.protocols import KnowledgeCacheProtocol, KnowledgeCluster

log = get_logger(__name__)

DEFAULT_CACHE_PATH = "data/.cache/knowledge"


class KnowledgeCache(KnowledgeCacheProtocol):
    """Knowledge cluster cache using DuckDB + Parquet.

    Architecture:
    - DuckDB in-memory for fast read/write
    - Parquet file for durable persistence
    - Daemon thread for periodic sync
    - FIFO queue for query management

    Implements: KnowledgeCacheProtocol

    Storage Path: {cache_path}/knowledge_clusters.parquet
    """

    def __init__(
        self,
        cache_path: str | None = None,
        llm_client: Any = None,
        sync_interval: int = 60,
        sync_threshold: int = 100,
        max_queries: int = 5,
    ) -> None:
        """Initialize the knowledge cache.

        Args:
            cache_path: Base path for cache storage.
            llm_client: LLMClient for computing embeddings via embed() method.
            sync_interval: Seconds between Parquet syncs.
            sync_threshold: Dirty count triggering immediate sync.
            max_queries: Maximum queries in FIFO queue per cluster.
        """
        # Setup paths
        if cache_path is None:
            cache_path = os.getenv("KNOWLEDGE_CACHE_PATH", DEFAULT_CACHE_PATH)
        self.cache_path = Path(cache_path).expanduser().resolve()
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.parquet_file = str(self.cache_path / "knowledge_clusters.parquet")

        # LLM Client for embedding
        self._llm_client = llm_client

        # DuckDB in-memory
        self.db = duckdb.connect(":memory:")
        self.table_name = validate_sql_identifier("knowledge_clusters", "table_name")

        # FIFO queue management
        self._max_queries = max_queries

        # Sync state
        self._dirty_count = 0
        self._sync_threshold = sync_threshold
        self._sync_lock = threading.RLock()
        self._stop_event = threading.Event()

        # Initialize table
        self._create_table()

        # Load from parquet if exists
        self._load_from_parquet()

        # Start sync daemon
        self._start_sync_daemon(sync_interval)
        atexit.register(self._shutdown)

        log.info(
            "knowledge_cache_initialized",
            path=str(self.cache_path),
            parquet_file=self.parquet_file,
        )

    def _create_table(self) -> None:
        """Create the knowledge clusters table with explicit schema."""
        self.db.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                description VARCHAR,
                content VARCHAR,
                embedding FLOAT[384],
                query VARCHAR,
                hotness FLOAT DEFAULT 0.5,
                create_time TIMESTAMP,
                last_modified TIMESTAMP,
                version INTEGER DEFAULT 0
            )
        """)

    def _load_from_parquet(self) -> None:
        """Load clusters from parquet file if exists."""
        try:
            pq = Path(self.parquet_file)
            if pq.exists():
                self.db.execute(
                    f"INSERT INTO {self.table_name} "
                    f"SELECT * FROM read_parquet('{self.parquet_file}')"
                )
                count = self.db.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()[0]
                log.info("loaded_clusters_from_parquet", count=count)
        except Exception as e:
            log.warning("failed_to_load_parquet", error=str(e))

    def _sync_to_parquet(self) -> None:
        """Sync in-memory data to parquet file."""
        with self._sync_lock:
            try:
                # Atomic write pattern
                temp_file = self.parquet_file + ".tmp"
                self.db.execute(f"COPY {self.table_name} TO '{temp_file}' (FORMAT PARQUET)")
                os.replace(temp_file, self.parquet_file)
                self._dirty_count = 0
                log.debug("synced_to_parquet")
            except Exception as e:
                log.error("parquet_sync_failed", error=str(e))

    def _mark_dirty(self) -> None:
        """Mark cache as dirty and maybe trigger sync."""
        with self._sync_lock:
            self._dirty_count += 1
            if self._dirty_count >= self._sync_threshold:
                self._sync_to_parquet()

    def _start_sync_daemon(self, interval: int) -> None:
        """Start background sync thread."""

        def sync_loop() -> None:
            while not self._stop_event.wait(interval):
                if self._dirty_count > 0:
                    self._sync_to_parquet()

        self._sync_thread = threading.Thread(target=sync_loop, daemon=True)
        self._sync_thread.start()

    def _shutdown(self) -> None:
        """Shutdown sync thread and do final sync."""
        self._stop_event.set()
        if self._dirty_count > 0:
            self._sync_to_parquet()

    def close(self) -> None:
        """Close DuckDB connection and stop sync thread.

        Call this explicitly to release resources when done with the cache.
        """
        self._shutdown()
        if hasattr(self, "db") and self.db is not None:
            try:
                self.db.close()
            except Exception as exc:
                log.warning(
                    "knowledge_cache_close_failed",
                    error=str(exc),
                    exc_type=type(exc).__name__,
                )
            self.db = None

    # ------------------------------------------------------------------
    # KnowledgeCacheProtocol implementation
    # ------------------------------------------------------------------

    async def find_similar_cluster(
        self,
        query: str,
        threshold: float = 0.75,
    ) -> KnowledgeCluster | None:
        """Find similar cluster by query embedding.

        Args:
            query: Search query.
            threshold: Minimum cosine similarity.

        Returns:
            KnowledgeCluster if found, None otherwise.
        """
        if self._llm_client is None:
            return None

        try:
            # Compute query embedding via LLM Client
            query_embeddings = await self._llm_client.embed_default([query])
            query_embedding = query_embeddings[0]

            # Search using DuckDB cosine similarity
            result = self.db.execute(f"""
                SELECT id, name, description, content, embedding, query, hotness,
                       create_time, last_modified, version,
                       list_cosine_similarity(embedding, {query_embedding}::FLOAT[384]) AS similarity
                FROM {self.table_name}
                WHERE embedding IS NOT NULL
                ORDER BY similarity DESC
                LIMIT 1
            """).fetchone()

            if result and result[10] >= threshold:
                similarity = result[10]
                # 分级置信度: >= 0.85 为 high, 0.75 ~ 0.85 为 medium
                confidence = "high" if similarity >= 0.85 else "medium"
                cluster = KnowledgeCluster(
                    id=result[0],
                    name=result[1],
                    description=result[2] or "",
                    content=result[3] or "",
                    embedding=list(result[4]) if result[4] else None,
                    query=result[5] or "",
                    hotness=result[6] or 0.5,
                    create_time=result[7],
                    last_modified=result[8],
                    version=result[9] or 0,
                )
                log.info(
                    "cache_hit",
                    cluster_id=cluster.id,
                    similarity=similarity,
                    query=query[:50],
                    confidence=confidence,
                )
                return cluster

            log.debug("cache_miss", query=query[:50], threshold=threshold)
            return None

        except Exception as e:
            log.error("find_similar_cluster_failed", error=str(e))
            return None

    async def store_cluster(self, cluster: KnowledgeCluster) -> str:
        """Store or update a cluster.

        Args:
            cluster: Cluster to store.

        Returns:
            Cluster ID.
        """
        try:
            # Compute embedding if not provided
            if cluster.embedding is None and self._llm_client:
                embeddings = await self._llm_client.embed_default(
                    [cluster.query or cluster.description]
                )
                cluster.embedding = embeddings[0]

            # Check if exists
            existing = self.db.execute(
                f"SELECT id FROM {self.table_name} WHERE id = ?",
                [cluster.id],
            ).fetchone()

            now = datetime.now(UTC)
            cluster.last_modified = now

            if existing:
                # Update
                self.db.execute(
                    f"""
                    UPDATE {self.table_name}
                    SET name = ?, description = ?, content = ?, embedding = ?,
                        query = ?, hotness = ?, last_modified = ?, version = version + 1
                    WHERE id = ?
                    """,
                    [
                        cluster.name,
                        cluster.description,
                        cluster.content,
                        cluster.embedding,
                        cluster.query,
                        cluster.hotness,
                        cluster.last_modified,
                        cluster.id,
                    ],
                )
                log.debug("cluster_updated", cluster_id=cluster.id)
            else:
                # Insert
                if cluster.create_time is None:
                    cluster.create_time = now
                self.db.execute(
                    f"""
                    INSERT INTO {self.table_name}
                    (id, name, description, content, embedding, query, hotness,
                     create_time, last_modified, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    [
                        cluster.id,
                        cluster.name,
                        cluster.description,
                        cluster.content,
                        cluster.embedding,
                        cluster.query,
                        cluster.hotness,
                        cluster.create_time,
                        cluster.last_modified,
                    ],
                )
                log.debug("cluster_inserted", cluster_id=cluster.id)

            self._mark_dirty()
            return cluster.id

        except Exception as e:
            log.error("store_cluster_failed", error=str(e), cluster_id=cluster.id)
            raise

    async def get(self, cluster_id: str) -> KnowledgeCluster | None:
        """Get cluster by ID.

        Args:
            cluster_id: Cluster ID.

        Returns:
            KnowledgeCluster if found, None otherwise.
        """
        try:
            result = self.db.execute(
                f"""
                SELECT id, name, description, content, embedding, query, hotness,
                       create_time, last_modified, version
                FROM {self.table_name}
                WHERE id = ?
                """,
                [cluster_id],
            ).fetchone()

            if result:
                return KnowledgeCluster(
                    id=result[0],
                    name=result[1],
                    description=result[2] or "",
                    content=result[3] or "",
                    embedding=list(result[4]) if result[4] else None,
                    query=result[5] or "",
                    hotness=result[6] or 0.5,
                    create_time=result[7],
                    last_modified=result[8],
                    version=result[9] or 0,
                )
            return None

        except Exception as e:
            log.error("get_cluster_failed", error=str(e), cluster_id=cluster_id)
            return None

    async def remove(self, cluster_id: str) -> bool:
        """Remove cluster by ID.

        Args:
            cluster_id: Cluster ID.

        Returns:
            True if removed, False if not found.
        """
        try:
            result = self.db.execute(
                f"DELETE FROM {self.table_name} WHERE id = ?",
                [cluster_id],
            )
            removed = result.fetchone()[0] > 0 if result else False
            if removed:
                self._mark_dirty()
                log.debug("cluster_removed", cluster_id=cluster_id)
            return removed

        except Exception as e:
            log.error("remove_cluster_failed", error=str(e))
            return False

    async def cleanup_stale(self, hotness_threshold: float = 0.3) -> int:
        """Remove clusters below hotness threshold.

        Args:
            hotness_threshold: Minimum hotness to keep.

        Returns:
            Number of clusters removed.
        """
        try:
            result = self.db.execute(
                f"DELETE FROM {self.table_name} WHERE hotness < ?",
                [hotness_threshold],
            )
            removed = result.fetchone()[0] if result else 0
            if removed > 0:
                self._mark_dirty()
                log.info("cleanup_stale_clusters", removed=removed)
            return removed

        except Exception as e:
            log.error("cleanup_stale_failed", error=str(e))
            return 0

    async def decay_hotness(self, decay_factor: float = 0.95) -> int:
        """Decay hotness of all clusters with hotness > 0.

        Multiplies hotness by decay_factor for all clusters where hotness > 0,
        then triggers persistence if any records were affected.

        Args:
            decay_factor: Multiplicative decay factor (default: 0.95 = 5% reduction).

        Returns:
            Number of clusters decayed.
        """
        try:
            # Count records that will be affected
            count_result = self.db.execute(
                f"SELECT COUNT(*) FROM {self.table_name} WHERE hotness > 0"
            ).fetchone()
            affected = count_result[0] if count_result else 0

            if affected > 0:
                self.db.execute(
                    f"UPDATE {self.table_name} SET hotness = hotness * ?",
                    [decay_factor],
                )
                self._mark_dirty()
                log.info("decay_hotness_complete", decayed=affected)

            return affected

        except Exception as e:
            log.error("decay_hotness_failed", error=str(e))
            return 0

    async def update_hotness(self, cluster_id: str, delta: float = 0.1) -> None:
        """Update cluster hotness.

        Args:
            cluster_id: Cluster ID.
            delta: Hotness increment.
        """
        try:
            self.db.execute(
                f"""
                UPDATE {self.table_name}
                SET hotness = LEAST(1.0, hotness + ?), last_modified = ?
                WHERE id = ?
                """,
                [delta, datetime.now(UTC), cluster_id],
            )
            self._mark_dirty()

        except Exception as e:
            log.error("update_hotness_failed", error=str(e))

    # ------------------------------------------------------------------
    # FIFO Query Queue Management
    # ------------------------------------------------------------------

    async def add_query(self, cluster_id: str, query: str) -> None:
        """Add a query to cluster's query history (FIFO management).

        Args:
            cluster_id: Cluster ID.
            query: Query to add.
        """
        try:
            # Get current queries
            result = self.db.execute(
                f"SELECT query FROM {self.table_name} WHERE id = ?",
                [cluster_id],
            ).fetchone()

            if result:
                queries = result[0].split("\n") if result[0] else []
                queries.append(query)
                # FIFO: keep only last N queries
                queries = queries[-self._max_queries :]

                self.db.execute(
                    f"UPDATE {self.table_name} SET query = ? WHERE id = ?",
                    ["\n".join(queries), cluster_id],
                )
                self._mark_dirty()

        except Exception as e:
            log.error("add_query_failed", error=str(e))

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with count, avg_hotness, etc.
        """
        try:
            result = self.db.execute(f"""
                SELECT
                    COUNT(*) as count,
                    AVG(hotness) as avg_hotness,
                    COUNT(CASE WHEN embedding IS NOT NULL THEN 1 END) as with_embedding
                FROM {self.table_name}
            """).fetchone()

            return {
                "count": result[0] or 0,
                "avg_hotness": result[1] or 0.0,
                "with_embedding": result[2] or 0,
            }

        except Exception as e:
            log.error("get_stats_failed", error=str(e))
            return {"count": 0, "avg_hotness": 0.0, "with_embedding": 0}


__all__ = [
    "KnowledgeCache",
]

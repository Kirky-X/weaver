#!/usr/bin/env python
"""Process pending articles and sync to LadybugDB.

Usage:
    uv run scripts/process_pending_articles.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


from config.settings import Settings
from container import Container
from core.db.models import PersistStatus
from core.observability.logging import get_logger

log = get_logger("process_pending")


async def process_pending_articles() -> int:
    """Process all pending articles and sync to LadybugDB."""
    settings = Settings()
    container = Container().configure(settings)
    await container.startup()

    # Get services
    article_repo = container.article_repo()
    graph_writer = container.graph_writer()
    vector_repo = container.vector_repo()
    pipeline = container.pipeline()

    # Use the existing DuckDB pool instead of creating a new connection
    relational_pool = container.relational_pool()

    # Get pending articles using the pool
    async with relational_pool.session() as session:
        from sqlalchemy import text

        result = await session.execute(text("""
            SELECT CAST(id AS VARCHAR) as id, title
            FROM articles
            WHERE persist_status = 'pending'
            ORDER BY created_at
        """))
        rows = result.fetchall()

    print(f"找到 {len(rows)} 篇待处理文章")

    processed_count = 0

    for row in rows:
        article_id = row[0]
        title = row[1]

        print(f"\n处理文章: {title[:50]}...")

        try:
            # 使用 pipeline 的 process_article_phase3 方法处理
            state = await pipeline.process_article_phase3(
                article_id=article_id, force_reprocess=True
            )

            print(f"  ✓ Phase3 完成")

            # 手动执行 persist 步骤 (因为 process_article_phase3 不包含 persist)
            # Phase4: Persist to PostgreSQL and LadybugDB
            if not state.get("terminal"):
                # Update article in DuckDB
                article_id_uuid = uuid.UUID(article_id)
                await article_repo.upsert(state)
                await article_repo.update_persist_status(article_id_uuid, PersistStatus.PG_DONE)
                print(f"  ✓ PG 持久化完成")

                # Write to LadybugDB
                if graph_writer:
                    neo4j_ids = await graph_writer.write(state)
                    state["neo4j_ids"] = neo4j_ids
                    await article_repo.update_persist_status(
                        article_id_uuid, PersistStatus.NEO4J_DONE
                    )
                    print(f"  ✓ Neo4j/LadybugDB 持久化完成")

                # Upsert vectors
                if vector_repo and "vectors" in state:
                    vectors = state["vectors"]
                    if isinstance(vectors, dict) and "title" in vectors and "content" in vectors:
                        await vector_repo.upsert_article_vectors(
                            article_id=article_id_uuid,
                            title_embedding=vectors.get("title"),
                            content_embedding=vectors.get("content"),
                            model_id=vectors.get("model_id", "unknown"),
                        )
                        print(f"  ✓ 向量持久化完成")

            processed_count += 1

        except Exception as exc:
            print(f"  ✗ 处理失败: {exc}")
            log.error("process_pending_failed", article_id=article_id, error=str(exc))

    await container.shutdown()

    print(f"\n处理完成: {processed_count}/{len(rows)} 篇")
    return processed_count


if __name__ == "__main__":
    count = asyncio.run(process_pending_articles())
    sys.exit(0 if count > 0 else 1)

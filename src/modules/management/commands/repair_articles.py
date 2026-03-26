# Copyright (c) 2026 KirkyX. All Rights Reserved
"""repair-articles command — fix incomplete terminal-path articles.

Scans articles with persist_status=NEO4J_DONE but NULL enrichment fields
and re-runs the enrichment pipeline to backfill missing data.

Only writes to PostgreSQL (idempotent). Does NOT modify Neo4j nodes.

Usage:
    python -m src.modules.management repair-articles [--limit N] [--force]
    python scripts/repair_articles.py [--limit N] [--force]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure project root is on path for `python -m src.modules.management` invocation
# File: src/modules/management/commands/repair_articles.py
# parents[5] = /home/dev/projects/weaver/src/  (project src/ dir)
_project_root = Path(__file__).resolve().parents[5]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config.settings import Settings  # noqa: E402
from core.cache import RedisClient  # noqa: E402
from core.db import PostgresPool  # noqa: E402
from core.event.bus import EventBus  # noqa: E402
from core.llm.client import LLMClient  # noqa: E402
from core.llm.config_manager import LLMConfigManager  # noqa: E402
from core.llm.queue_manager import LLMQueueManager  # noqa: E402
from core.llm.rate_limiter import RedisTokenBucket  # noqa: E402
from core.llm.token_budget import TokenBudgetManager  # noqa: E402
from core.observability.logging import get_logger  # noqa: E402
from core.prompt.loader import PromptLoader  # noqa: E402
from modules.collector.models import ArticleRaw  # noqa: E402
from modules.nlp.spacy_extractor import SpacyExtractor  # noqa: E402
from modules.pipeline.graph import Pipeline  # noqa: E402
from modules.pipeline.state import PipelineState  # noqa: E402

log = get_logger("repair_articles")


async def _init_minimal_container():
    """Initialize only the services needed for repair (no crawler/scheduler)."""
    settings = Settings()

    postgres_pool = PostgresPool(settings.postgres.dsn)
    await postgres_pool.startup()
    log.info(
        "postgres_initialized",
        dsn=(
            str(settings.postgres.dsn).split("@")[1] if "@" in str(settings.postgres.dsn) else "..."
        ),
    )

    redis_client = RedisClient(settings.redis.url)
    await redis_client.startup()
    log.info("redis_initialized")

    config_manager = LLMConfigManager(settings.llm)
    rate_limiter = RedisTokenBucket(redis_client.client)
    event_bus = EventBus()
    queue_manager = LLMQueueManager(
        config_manager=config_manager,
        rate_limiter=rate_limiter,
        event_bus=event_bus,
    )
    await queue_manager.startup()
    log.info("llm_queue_manager_started")

    prompt_loader = PromptLoader(settings.prompt.dir)
    token_budget = TokenBudgetManager()
    llm_client = LLMClient(
        queue_manager=queue_manager,
        prompt_loader=prompt_loader,
        token_budget=token_budget,
    )
    log.info("llm_client_initialized")

    return postgres_pool, redis_client, llm_client, queue_manager, prompt_loader


async def _shutdown_minimal_container(postgres_pool, redis_client, queue_manager):
    """Shutdown minimal container services."""
    await queue_manager.shutdown()
    await redis_client.shutdown()
    await postgres_pool.shutdown()
    log.info("container_shutdown_complete")


async def repair_articles(limit: int = 10, force: bool = False, dry_run: bool = False) -> int:
    """Repair incomplete articles by re-running enrichment pipeline.

    Args:
        limit: Maximum articles to repair per batch.
        force: Process all incomplete articles regardless of limit.
        dry_run: Print what would be repaired without running pipeline.

    Returns:
        Number of articles repaired.
    """
    # Initialize minimal services
    postgres_pool, redis_client, llm_client, queue_manager, prompt_loader = (
        await _init_minimal_container()
    )

    try:
        from modules.storage.article_repo import ArticleRepo

        article_repo = ArticleRepo(postgres_pool)

        # Build pipeline with neo4j_writer=None (we only read from Neo4j, never write)
        spacy_extractor = SpacyExtractor()
        pipeline = Pipeline(
            llm=llm_client,
            budget=TokenBudgetManager(),
            prompt_loader=prompt_loader,
            event_bus=EventBus(),
            spacy=spacy_extractor,
            vector_repo=None,  # Not needed for repair (terminal articles skip vector ops)
            article_repo=article_repo,
            neo4j_writer=None,  # Idempotent: do NOT write to Neo4j
            source_auth_repo=None,
            entity_resolver=None,
            redis_client=redis_client,
        )

        repaired = 0
        total_checked = 0

        while True:
            articles = await article_repo.get_incomplete_articles(limit=limit)
            if not articles:
                break

            total_checked += len(articles)
            print(f"\nFound {len(articles)} incomplete articles (total checked: {total_checked})")

            if dry_run:
                for article in articles:
                    print(f"  [DRY RUN] Would repair: {article.title[:60] or '(no title)'}...")
                    print(
                        f"    id={article.id} | cat={article.category} | "
                        f"score={article.score} | cred={article.credibility_score} | "
                        f"summary={'present' if article.summary else 'NULL'}"
                    )
                repaired += len(articles)
            else:
                for article in articles:
                    title_preview = (article.title or "(no title)")[:60]
                    print(f"\nRepairing: {title_preview}...")
                    print(f"  id={article.id} | is_news={article.is_news}")

                    # Build minimal pipeline state for enrichment
                    # _phase3_per_article needs:
                    #   - state["cleaned"]["title"] and ["body"] for AnalyzeNode + QualityScorerNode
                    #   - state["is_news"] / state["terminal"] set appropriately
                    raw = ArticleRaw(
                        url=article.source_url,
                        title=article.title or "",
                        body=article.body or "",
                        source=article.source_host or "",
                        source_host=article.source_host or "",
                        publish_time=article.publish_time,
                    )

                    state: PipelineState = PipelineState(raw=raw)
                    state["article_id"] = str(article.id)
                    state["is_news"] = article.is_news
                    state["terminal"] = not article.is_news
                    state["cleaned"] = {
                        "title": article.title or "",
                        "body": article.body or "",
                    }

                    try:
                        # Run phase3 enrichment only (phase3_per_article handles
                        # analyze + quality_scorer + credibility + entity_extractor)
                        enriched_state = await pipeline._phase3_per_article(state)

                        # Extract enrichment values from enriched state
                        enriched_category = enriched_state.get("category")
                        enriched_score = enriched_state.get("score")
                        enriched_cred_score = enriched_state.get("credibility", {}).get("score")
                        enriched_summary = enriched_state.get("summary_info", {}).get("summary")
                        enriched_quality = enriched_state.get("quality_score")

                        # Update only NULL fields (idempotent)
                        updated = await article_repo.update_enrichment_if_null(
                            article.id,
                            category=enriched_category,
                            score=enriched_score,
                            credibility_score=enriched_cred_score,
                            summary=enriched_summary,
                            quality_score=enriched_quality,
                        )

                        if updated:
                            repaired += 1
                            print(
                                f"  Repaired: category={enriched_category} | "
                                f"score={enriched_score} | cred={enriched_cred_score} | "
                                f"quality={enriched_quality}"
                            )
                        else:
                            print("  No fields updated (all already set or no enrichment produced)")

                    except Exception as e:
                        print(f"  FAILED: {type(e).__name__}: {e}")

            # Exit loop if not forcing (only process one batch per run by default)
            if not force:
                break

        print("\n=== Summary ===")
        print(f"Total articles checked: {total_checked}")
        print(f"Total articles repaired: {repaired}")
        return repaired

    finally:
        await _shutdown_minimal_container(postgres_pool, redis_client, queue_manager)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repair incomplete terminal-path articles (NEO4J_DONE but NULL enrichment)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max articles to repair per batch (default: 10)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Process all incomplete articles (default: stops after one batch)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be repaired without running the pipeline",
    )
    args = parser.parse_args()

    try:
        repaired = asyncio.run(
            repair_articles(limit=args.limit, force=args.force, dry_run=args.dry_run)
        )
        sys.exit(0)  # Always exit 0 (repair is non-critical)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nFatal error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

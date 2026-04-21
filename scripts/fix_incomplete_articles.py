#!/usr/bin/env python3
"""Fix incomplete articles that are missing LLM processing results.

This script finds articles in the database that are missing critical LLM
processing results (summary, score, or primary_emotion) and reprocesses
them through the pipeline.

Usage:
    # Preview mode - show articles that need fixing
    uv run scripts/fix_incomplete_articles.py --dry-run

    # Fix mode - reprocess all incomplete articles
    uv run scripts/fix_incomplete_articles.py --fix

    # Custom batch size and delay
    uv run scripts/fix_incomplete_articles.py --fix --batch-size 5 --delay 30

    # Use DuckDB instead of PostgreSQL
    uv run scripts/fix_incomplete_articles.py --dry-run --db duckdb

Modes:
    --dry-run: Preview mode - displays statistics and list of incomplete articles
               without making any changes to the database.

    --fix:     Execution mode - resubmits incomplete articles to the pipeline
               for reprocessing. Articles are processed in batches with configurable
               delays between batches to avoid rate limiting (429 errors).

Batch Processing:
    Articles are processed in batches to:
    - Manage memory usage
    - Avoid overwhelming the LLM API
    - Allow progress tracking
    - Enable graceful error recovery

    Default: 10 articles per batch with 60 second delay between batches.

Note: To limit physical memory, run with:
    systemd-run --scope -p MemoryMax=24G uv run scripts/fix_incomplete_articles.py --fix
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ─────────────────────────────────────────────────────────────────────────────
# Database Query Functions
# ─────────────────────────────────────────────────────────────────────────────


async def query_incomplete_articles_postgres(settings) -> list[dict[str, Any]]:
    """Query incomplete articles from PostgreSQL.

    Args:
        settings: Application settings with database connection info.

    Returns:
        List of article dicts with id, title, and persist_status.
    """
    from core.observability.logging import get_logger

    log = get_logger("fix_incomplete_articles")

    pg = settings.postgres
    dsn = f"postgresql://{pg.user}:{pg.password}@{pg.host}:{pg.port}/{pg.database}"

    print(f"正在查询 PostgreSQL 数据库...")
    log.info("querying_postgresql", database=pg.database)

    try:
        import asyncpg

        conn = await asyncpg.connect(dsn)

        # nosemgrep: python.sqlalchemy.security.audit sqlalchemy-execute-raw-query
        # Static query with no user input
        rows = await conn.fetch("""
            SELECT id, title, persist_status
            FROM articles
            WHERE summary IS NULL
               OR score IS NULL
               OR primary_emotion IS NULL
            ORDER BY created_at DESC
        """)

        articles = [
            {
                "id": str(row["id"]),
                "title": row["title"],
                "persist_status": row["persist_status"],
            }
            for row in rows
        ]

        await conn.close()

        log.info(
            "query_complete",
            article_count=len(articles),
            database="postgresql",
        )

        return articles

    except Exception as exc:
        log.error("postgresql_query_failed", error=str(exc))
        print(f"PostgreSQL 查询失败：{exc}")
        raise


async def query_incomplete_articles_duckdb(settings) -> list[dict[str, Any]]:
    """Query incomplete articles from DuckDB.

    Args:
        settings: Application settings with database connection info.

    Returns:
        List of article dicts with id, title, and persist_status.
    """
    from core.observability.logging import get_logger

    log = get_logger("fix_incomplete_articles")

    if not settings.duckdb.enabled:
        raise RuntimeError("DuckDB is not enabled")

    print(f"正在查询 DuckDB 数据库...")
    log.info("querying_duckdb", db_path=settings.duckdb.db_path)

    try:
        from sqlalchemy import text

        from core.db.duckdb_pool import DuckDBPool

        pool = DuckDBPool(db_path=settings.duckdb.db_path)
        await pool.startup()

        async with pool.session_context() as session:
            # nosemgrep: python.sqlalchemy.security.audit sqlalchemy-execute-raw-query
            # Static query with no user input
            result = await session.execute(text("""
                SELECT id, title, persist_status
                FROM articles
                WHERE summary IS NULL
                   OR score IS NULL
                   OR primary_emotion IS NULL
                ORDER BY created_at DESC
            """))

            rows = result.fetchall()
            columns = result.keys()

            articles = [
                {
                    "id": str(row[0]),
                    "title": row[1],
                    "persist_status": row[2],
                }
                for row in rows
            ]

        await pool.shutdown()

        log.info(
            "query_complete",
            article_count=len(articles),
            database="duckdb",
        )

        return articles

    except Exception as exc:
        log.error("duckdb_query_failed", error=str(exc))
        print(f"DuckDB 查询失败：{exc}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Article Processing
# ─────────────────────────────────────────────────────────────────────────────


async def process_article_batch(
    articles: list[dict[str, Any]],
    pipeline: Any,
    article_repo: Any,
    batch_num: int,
    total_batches: int,
) -> dict[str, Any]:
    """Process a batch of articles through the pipeline.

    Args:
        articles: List of article dicts to process.
        pipeline: Pipeline instance for processing.
        article_repo: Article repository for database access.
        batch_num: Current batch number (1-based).
        total_batches: Total number of batches.

    Returns:
        Dict with processing statistics.
    """
    from core.observability.logging import get_logger

    log = get_logger("fix_incomplete_articles")

    print(f"\n{'=' * 80}")
    print(f"批次 {batch_num}/{total_batches}: 处理 {len(articles)} 篇文章")
    print(f"{'=' * 80}")

    log.info(
        "batch_start",
        batch_num=batch_num,
        total_batches=total_batches,
        article_count=len(articles),
    )

    # Convert to RawArticle objects
    from modules.ingestion.domain.models import RawArticle

    raw_articles = []
    article_ids = []

    for article in articles:
        article_id = article["id"]
        try:
            # Fetch full article data
            article_obj = await article_repo.get_by_id(article_id)
            if article_obj is None:
                print(f"  ⚠ 文章 {article_id[:8]}... 不存在，跳过")
                log.warning("article_not_found", article_id=article_id)
                continue

            if not article_obj.body:
                print(f"  ⚠ 文章 {article_id[:8]}... 无正文，跳过")
                log.warning("article_no_body", article_id=article_id)
                continue

            # Check if already complete (skip if so)
            if (
                article_obj.summary is not None
                and article_obj.score is not None
                and article_obj.primary_emotion is not None
            ):
                print(f"  ✓ 文章 {article_id[:8]}... 已完成，跳过")
                log.info("article_already_complete", article_id=article_id)
                continue

            raw = RawArticle(
                url=article_obj.source_url,
                title=article_obj.title or "",
                body=article_obj.body,
                source=article_obj.source_host or "reprocess",
                source_host=article_obj.source_host or "",
                publish_time=article_obj.publish_time,
            )
            raw_articles.append(raw)
            article_ids.append(article_obj.id)

        except Exception as exc:
            print(f"  ✗ 准备文章 {article_id[:8]}... 失败：{exc}")
            log.error("article_prep_failed", article_id=article_id, error=str(exc))

    if not raw_articles:
        print("  没有需要处理的文章")
        log.info("batch_no_articles_to_process")
        return {"processed": 0, "success": 0, "failed": 0, "skipped": 0}

    print(f"\n实际处理 {len(raw_articles)} 篇文章...")

    # Process through pipeline
    try:
        task_id = uuid.uuid4()
        states = await pipeline.process_batch(
            raw_articles,
            article_ids=[str(aid) for aid in article_ids],
            task_id=task_id,
        )

        # Count results
        completed = sum(1 for s in states if not s.get("terminal"))
        failed = sum(1 for s in states if s.get("terminal"))
        skipped = len(raw_articles) - completed - failed

        print(f"\n批次结果：")
        print(f"  ✓ 成功：{completed}")
        print(f"  ✗ 失败：{failed}")
        if skipped > 0:
            print(f"  ⚠ 跳过：{skipped}")

        log.info(
            "batch_complete",
            batch_num=batch_num,
            completed=completed,
            failed=failed,
            skipped=skipped,
        )

        return {
            "processed": len(raw_articles),
            "success": completed,
            "failed": failed,
            "skipped": skipped,
        }

    except Exception as exc:
        print(f"\n  ✗ 批次处理失败：{exc}")
        log.error("batch_processing_failed", batch_num=batch_num, error=str(exc))
        return {
            "processed": len(raw_articles),
            "success": 0,
            "failed": len(raw_articles),
            "skipped": 0,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Dry Run Mode
# ─────────────────────────────────────────────────────────────────────────────


async def cmd_dry_run(args: argparse.Namespace) -> int:
    """Execute dry run - show statistics without processing.

    Args:
        args: Parsed command line arguments.

    Returns:
        Exit code (0 for success).
    """
    from config.settings import Settings
    from core.observability.logging import get_logger

    log = get_logger("fix_incomplete_articles")

    print("=" * 80)
    print("  修复不完整文章 - 预览模式")
    print("=" * 80)
    print(f"数据库：{args.db}")
    print()

    # Load settings
    settings = Settings()

    # Query incomplete articles
    try:
        if args.db == "postgres":
            articles = await query_incomplete_articles_postgres(settings)
        elif args.db == "duckdb":
            articles = await query_incomplete_articles_duckdb(settings)
        else:
            print(f"不支持的数据库类型：{args.db}")
            return 1
    except Exception as exc:
        log.error("query_failed", error=str(exc))
        print(f"\n查询失败：{exc}")
        return 1

    if not articles:
        print("\n✓ 没有找到需要修复的文章")
        return 0

    # Display statistics
    print(f"\n{'=' * 80}")
    print(f"统计信息")
    print(f"{'=' * 80}")
    print(f"不完整文章总数：{len(articles)}")

    # Count by persist_status
    status_counts: dict[str, int] = {}
    for article in articles:
        status = article["persist_status"] or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    print(f"\n按持久化状态分布：")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    # Display article list
    print(f"\n{'=' * 80}")
    print(f"文章列表 (最新在前)")
    print(f"{'=' * 80}")
    print(f"{'ID':<38} {'状态':<15} {'标题'}")
    print("-" * 80)

    for article in articles:
        article_id = article["id"]
        title = article["title"] or "无标题"
        status = article["persist_status"] or "unknown"

        # Truncate title if too long
        if len(title) > 50:
            title = title[:47] + "..."

        print(f"{article_id:<38} {status:<15} {title}")

    print(f"\n{'=' * 80}")
    print(f"执行修复命令：")
    print(f"  uv run scripts/fix_incomplete_articles.py --fix")
    print(f"\n自定义批次大小和延迟：")
    print(f"  uv run scripts/fix_incomplete_articles.py --fix --batch-size 5 --delay 30")
    print(f"{'=' * 80}")

    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Fix Mode
# ─────────────────────────────────────────────────────────────────────────────


async def cmd_fix(args: argparse.Namespace) -> int:
    """Execute fix - reprocess incomplete articles.

    Args:
        args: Parsed command line arguments.

    Returns:
        Exit code (0 for success, 1 for errors).
    """
    from config.settings import Settings
    from container import Container, set_container, set_settings
    from core.observability.logging import get_logger

    log = get_logger("fix_incomplete_articles")

    print("=" * 80)
    print("  修复不完整文章 - 执行模式")
    print("=" * 80)
    print(f"数据库：{args.db}")
    print(f"批次大小：{args.batch_size}")
    print(f"批次间隔：{args.delay}秒")
    print()

    # Load settings and create container
    settings = Settings()
    container = Container().configure(settings)
    set_container(container)
    set_settings(settings)

    try:
        # Initialize services
        await container.init_strategy()
        await container.init_llm()
        pipeline = await container.init_pipeline()
        relational_pool = container.relational_pool()

        # Create article repo
        from modules.storage import ArticleRepo

        article_repo = ArticleRepo(relational_pool)

        # Query incomplete articles
        try:
            if args.db == "postgres":
                articles = await query_incomplete_articles_postgres(settings)
            elif args.db == "duckdb":
                articles = await query_incomplete_articles_duckdb(settings)
            else:
                print(f"不支持的数据库类型：{args.db}")
                return 1
        except Exception as exc:
            log.error("query_failed", error=str(exc))
            print(f"\n查询失败：{exc}")
            return 1

        if not articles:
            print("\n✓ 没有找到需要修复的文章")
            return 0

        print(f"\n找到 {len(articles)} 篇需要修复的文章")

        # Split into batches
        batch_size = args.batch_size
        batches = [articles[i : i + batch_size] for i in range(0, len(articles), batch_size)]
        total_batches = len(batches)

        print(f"分为 {total_batches} 个批次（每批 {batch_size} 篇）")

        # Process batches
        total_processed = 0
        total_success = 0
        total_failed = 0
        total_skipped = 0

        for batch_num, batch in enumerate(batches, 1):
            result = await process_article_batch(
                batch,
                pipeline,
                article_repo,
                batch_num,
                total_batches,
            )

            total_processed += result["processed"]
            total_success += result["success"]
            total_failed += result["failed"]
            total_skipped += result["skipped"]

            # Delay between batches (not after the last one)
            if batch_num < total_batches:
                print(f"\n等待 {args.delay} 秒后处理下一批...")
                log.info(
                    "batch_delay",
                    delay_seconds=args.delay,
                    next_batch=batch_num + 1,
                )
                await asyncio.sleep(args.delay)

        # Print final summary
        print(f"\n{'=' * 80}")
        print(f"修复完成 - 最终统计")
        print(f"{'=' * 80}")
        print(f"总文章数：{len(articles)}")
        print(f"已处理：{total_processed}")
        print(f"成功：{total_success}")
        print(f"失败：{total_failed}")
        print(f"跳过（已完整）：{total_skipped}")

        log.info(
            "fix_complete",
            total_articles=len(articles),
            processed=total_processed,
            success=total_success,
            failed=total_failed,
            skipped=total_skipped,
        )

        # Return appropriate exit code
        if total_failed > 0:
            print(f"\n⚠ 有 {total_failed} 篇文章处理失败")
            return 1

        return 0

    except Exception as exc:
        print(f"\n✗ 修复过程失败：{exc}")
        log.error("fix_fatal", error=str(exc))
        import traceback

        traceback.print_exc()
        return 1

    finally:
        await container.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    """Main entry point for the script.

    Returns:
        Exit code (0 for success, 1 for errors).
    """
    parser = argparse.ArgumentParser(
        description="修复数据库中未完成LLM处理的文章",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
    # 预览需要修复的文章
    uv run scripts/fix_incomplete_articles.py --dry-run

    # 执行修复
    uv run scripts/fix_incomplete_articles.py --fix

    # 自定义批次大小和延迟
    uv run scripts/fix_incomplete_articles.py --fix --batch-size 5 --delay 30

    # 使用 DuckDB 数据库
    uv run scripts/fix_incomplete_articles.py --dry-run --db duckdb
        """,
    )

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式：显示需要修复的文章列表和统计信息，不执行实际修复",
    )
    mode_group.add_argument(
        "--fix",
        action="store_true",
        dest="fix_mode",
        help="执行模式：重新提交文章到pipeline进行处理",
    )

    # Optional parameters
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="每批处理的文章数量（默认：10）",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=60,
        help="批次间隔秒数，避免429限流（默认：60秒）",
    )
    parser.add_argument(
        "--db",
        choices=["postgres", "duckdb"],
        default="postgres",
        help="数据库类型（默认：postgres）",
    )

    args = parser.parse_args()

    # Dispatch to appropriate command
    if args.dry_run:
        return asyncio.run(cmd_dry_run(args))
    elif args.fix_mode:
        return asyncio.run(cmd_fix(args))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

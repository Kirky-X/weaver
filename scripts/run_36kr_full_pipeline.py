#!/usr/bin/env python3
"""完整的36kr数据采集和处理流程脚本。

执行步骤:
1. 清空所有数据库数据
2. 注册36kr数据源
3. 从36kr采集所有可用文章
4. 通过完整pipeline处理所有文章
5. 统计和验证最终结果

Usage:
    python scripts/run_36kr_full_pipeline.py
"""

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.config.settings import Settings
from src.container import Container
from src.core.observability.logging import get_logger

log = get_logger("36kr_pipeline")


class Colors:
    """终端颜色输出。"""

    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    RED = "\033[0;31m"
    BOLD = "\033[1m"
    NC = "\033[0m"


def print_header(text: str):
    """打印标题。"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 80}{Colors.NC}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text:^80}{Colors.NC}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 80}{Colors.NC}\n")


def print_step(step_num: int, total: int, text: str):
    """打印步骤。"""
    print(f"{Colors.CYAN}[步骤 {step_num}/{total}]{Colors.NC} {Colors.BOLD}{text}{Colors.NC}")
    print(f"{Colors.CYAN}{'─' * 80}{Colors.NC}")


def print_success(text: str):
    """打印成功信息。"""
    print(f"{Colors.GREEN}✓ {text}{Colors.NC}")


def print_info(text: str):
    """打印信息。"""
    print(f"{Colors.CYAN}  ℹ {text}{Colors.NC}")


def print_warning(text: str):
    """打印警告。"""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.NC}")


def print_error(text: str):
    """打印错误。"""
    print(f"{Colors.RED}✗ {text}{Colors.NC}")


async def clear_all_data(container: Container):
    """清空所有数据库数据。"""
    print_step(1, 5, "清空所有数据库数据")

    try:
        # 清空 Neo4j (可选)
        print_info("正在清空 Neo4j 图数据库...")
        try:
            neo4j_pool = container.neo4j_pool()
            await neo4j_pool.startup()
            await neo4j_pool.execute_query("MATCH (n) DETACH DELETE n")
            print_success("Neo4j 已清空")
        except Exception as neo4j_error:
            print_warning(f"Neo4j 清空失败（将继续执行）: {neo4j_error}")

        # 清空 PostgreSQL
        print_info("正在清空 PostgreSQL 数据库...")
        postgres_pool = container.postgres_pool()
        async with postgres_pool.session() as session:
            # 清空所有表 (按照外键依赖顺序)
            from sqlalchemy import text

            await session.execute(text("DELETE FROM article_vectors"))
            await session.execute(text("DELETE FROM entity_vectors"))
            await session.execute(text("DELETE FROM llm_failures"))
            await session.execute(text("DELETE FROM articles"))
            await session.execute(text("DELETE FROM source_authorities"))
            await session.execute(text("DELETE FROM sources"))
            await session.commit()
        print_success("PostgreSQL 已清空")

        # 清空 Redis
        print_info("正在清空 Redis 缓存...")
        redis_client = container.redis_client()
        await redis_client.client.flushdb()
        print_success("Redis 已清空")

        print_success("所有数据库已清空")
        return True

    except Exception as e:
        print_error(f"清空数据库失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def register_36kr_source(container: Container):
    """注册36kr数据源。"""
    print_step(2, 5, "注册36kr数据源")

    try:
        source_config_repo = container.source_config_repo()

        # 检查是否已存在
        existing = await source_config_repo.get("36kr")
        if existing:
            print_warning("36kr 数据源已存在，将删除并重新注册")
            await source_config_repo.delete("36kr")

        # 注册新数据源
        from modules.source.models import SourceConfig

        source_data = SourceConfig(
            id="36kr",
            name="36氪",
            url="https://www.newsnow.world/api/s?id=36kr",
            source_type="newsnow",
            enabled=True,
            interval_minutes=30,
            per_host_concurrency=2,
        )

        await source_config_repo.upsert(source_data)
        print_success("36kr 数据源注册成功")
        print_info(f"  - ID: {source_data.id}")
        print_info(f"  - 名称: {source_data.name}")
        print_info(f"  - URL: {source_data.url}")
        print_info(f"  - 类型: {source_data.source_type}")

        return True

    except Exception as e:
        print_error(f"注册数据源失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def fetch_36kr_articles(container: Container) -> int:
    """从36kr采集所有可用文章。"""
    print_step(3, 5, "从36kr采集所有可用文章")

    try:
        source_registry = container.source_registry()
        crawler = container.crawler()
        deduplicator = container.deduplicator()
        article_repo = container.article_repo()

        source_config_repo = container.source_config_repo()
        source = await source_config_repo.get("36kr")

        if not source:
            print_error("36kr 数据源不存在")
            return 0

        print_info("正在获取新闻列表...")
        print_info(f"正在从 {source.url} 获取...")

        # 获取 parser
        parser = source_registry.get_parser(source.source_type)
        if not parser:
            print_error(f"找不到 {source.source_type} 类型的 parser")
            return 0

        # 解析新闻列表
        news_items = await parser.parse(source)
        print_info(f"获取到 {len(news_items)} 篇文章")

        if not news_items:
            print_warning("未找到任何文章")
            return 0

        # 批量爬取文章内容
        print_info("正在爬取文章内容...")
        crawl_results = await crawler.crawl_batch(
            news_items, per_host_config={source.url: source.per_host_concurrency}
        )

        # 过滤成功的文章
        successful_articles = [r for r in crawl_results if hasattr(r, "url")]
        failed_count = len(crawl_results) - len(successful_articles)

        print_info(f"成功爬取 {len(successful_articles)} 篇文章")

        # 批量去重
        print_info("正在检查重复...")
        new_articles = await deduplicator.dedup(successful_articles)
        duplicate_count = len(successful_articles) - len(new_articles)

        if duplicate_count > 0:
            print_info(f"过滤 {duplicate_count} 篇重复文章")

        # 批量保存
        fetch_count = 0
        for article in new_articles:
            await article_repo.insert_raw(article)
            fetch_count += 1
            if fetch_count % 10 == 0:
                print_info(f"已保存 {fetch_count} 篇文章...")

        print_success(f"采集完成，共获取 {fetch_count} 篇新文章")
        if failed_count > 0:
            print_warning(f"失败 {failed_count} 篇")
        return fetch_count

    except Exception as e:
        print_error(f"采集失败: {e}")
        import traceback

        traceback.print_exc()
        return 0


async def process_pipeline(container: Container, article_count: int) -> dict:
    """执行完整的pipeline处理流程。"""
    print_step(4, 5, "执行完整pipeline处理流程")

    try:
        pipeline = container.pipeline()
        article_repo = container.article_repo()

        print_info(f"开始处理 {article_count} 篇文章...")
        print_info(
            "处理阶段：分类 → 清洗 → 分类 → 向量化 → 分析 → 质量评分 → 可信度 → 实体提取 → 存储"
        )

        # 获取所有待处理文章
        postgres_pool = container.postgres_pool()
        async with postgres_pool.session() as session:
            from sqlalchemy import text

            result = await session.execute(
                text(
                    "SELECT id FROM articles WHERE persist_status = 'pending' ORDER BY created_at DESC"
                )
            )
            article_ids = [row[0] for row in result.fetchall()]

        if not article_ids:
            print_warning("没有待处理的文章")
            return {"total": 0, "success": 0, "failed": 0}

        stats = {"total": len(article_ids), "success": 0, "failed": 0}

        print_info(f"开始处理 {stats['total']} 篇文章...")

        # 批量获取文章数据
        articles_raw = []
        valid_article_ids = []

        for article_id in article_ids:
            article_data = await article_repo.get(article_id)
            if article_data:
                from modules.collector.models import ArticleRaw

                raw = ArticleRaw(
                    url=article_data.source_url,
                    title=article_data.title,
                    body=article_data.body,
                    source_host=article_data.source_host,
                    publish_time=article_data.publish_time,
                )
                articles_raw.append(raw)
                valid_article_ids.append(article_id)

        print_info(f"准备处理 {len(articles_raw)} 篇文章...")

        # 批量执行 pipeline
        result_states = await pipeline.process_batch(articles_raw, valid_article_ids)

        # 统计结果
        for idx, state in enumerate(result_states, 1):
            if state.get("terminal"):
                print_info(f"[{idx}/{len(result_states)}] 文章被标记为非新闻")
                stats["success"] += 1
            elif state.get("error"):
                print_error(f"[{idx}/{len(result_states)}] 文章处理出错: {state.get('error')}")
                stats["failed"] += 1
            else:
                stats["success"] += 1

            if idx % 5 == 0:
                print_success(f"已完成 {idx}/{len(result_states)} 篇文章")

        print_success(f"Pipeline 处理完成")
        print_info(f"  - 总计: {stats['total']} 篇")
        print_info(f"  - 成功: {stats['success']} 篇")
        print_info(f"  - 失败: {stats['failed']} 篇")

        return stats

    except Exception as e:
        print_error(f"Pipeline 处理失败: {e}")
        import traceback

        traceback.print_exc()
        return {"total": 0, "success": 0, "failed": 0}


async def verify_results(container: Container) -> dict:
    """统计和验证最终结果。"""
    print_step(5, 5, "统计和验证最终结果")

    try:
        stats = {}

        # PostgreSQL 统计
        print_info("PostgreSQL 数据统计:")
        postgres_pool = container.postgres_pool()
        async with postgres_pool.session() as session:
            from sqlalchemy import text

            # 文章统计
            result = await session.execute(text("SELECT COUNT(*) FROM articles"))
            stats["articles_total"] = result.scalar() or 0
            print_info(f"  - 文章总数: {stats['articles_total']}")

            # 按状态统计
            result = await session.execute(text("""
                SELECT persist_status, COUNT(*) as count
                FROM articles
                GROUP BY persist_status
            """))
            for row in result:
                print_info(f"  - {row[0]}: {row[1]} 篇")

            # 向量统计
            result = await session.execute(text("SELECT COUNT(*) FROM article_vectors"))
            stats["vectors_total"] = result.scalar() or 0
            print_info(f"  - 向量总数: {stats['vectors_total']}")

        # Neo4j 统计
        print_info("Neo4j 图数据库统计:")
        neo4j_pool = container.neo4j_pool()

        try:
            # 节点统计
            result = await neo4j_pool.execute_query("""
                MATCH (n)
                RETURN labels(n)[0] as label, count(*) as count
                ORDER BY count DESC
            """)
            node_count = 0
            for record in result:
                label = record.get("label", "Unknown")
                count = record.get("count", 0)
                print_info(f"  - {label} 节点: {count} 个")
                node_count += count

            # 关系统计
            result = await neo4j_pool.execute_query("""
                MATCH ()-[r]->()
                RETURN type(r) as type, count(*) as count
                ORDER BY count DESC
            """)
            rel_count = 0
            for record in result:
                rel_type = record.get("type", "Unknown")
                count = record.get("count", 0)
                print_info(f"  - {rel_type} 关系: {count} 个")
                rel_count += count

            stats["neo4j_nodes"] = node_count
            stats["neo4j_relationships"] = rel_count
        except Exception as neo4j_error:
            print_warning(f"Neo4j 统计失败（将继续执行）: {neo4j_error}")
            stats["neo4j_nodes"] = 0
            stats["neo4j_relationships"] = 0

        return stats

    except Exception as e:
        print_error(f"统计失败: {e}")
        import traceback

        traceback.print_exc()
        return {}


async def main():
    """主函数。"""
    start_time = time.time()

    print_header("36kr 完整数据采集和处理流程")

    print_info(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    try:
        # 初始化容器
        print_info("正在初始化容器...")
        settings = Settings()
        container = Container()
        container.configure(settings)
        await container.startup()

        # 执行流程
        success = True
        article_count = 0
        pipeline_stats = {}
        final_stats = {}

        # 1. 清空数据
        if not await clear_all_data(container):
            success = False
        else:
            await asyncio.sleep(1)  # 等待数据库清空完成

            # 2. 注册数据源
            if not await register_36kr_source(container):
                success = False
            else:
                await asyncio.sleep(1)

                # 3. 采集文章
                article_count = await fetch_36kr_articles(container)

                if article_count == 0:
                    print_warning("未采集到任何文章，跳过 pipeline 处理")
                else:
                    await asyncio.sleep(2)

                    # 4. 执行 pipeline
                    pipeline_stats = await process_pipeline(container, article_count)

                    await asyncio.sleep(1)

                    # 5. 验证结果
                    final_stats = await verify_results(container)

        # 关闭容器
        await container.shutdown()

        # 最终总结
        elapsed_time = time.time() - start_time
        print()
        print_header("执行完成")

        if success:
            print_success(f"总耗时: {elapsed_time:.2f} 秒 ({elapsed_time/60:.1f} 分钟)")
            print()
            if article_count > 0:
                print_success(f"✓ 采集文章: {article_count} 篇")
                print_success(f"✓ 处理成功: {pipeline_stats.get('success', 0)} 篇")
                if pipeline_stats.get("failed", 0) > 0:
                    print_warning(f"✗ 处理失败: {pipeline_stats.get('failed', 0)} 篇")
                print_success(f"✓ 最终文章数: {final_stats.get('articles_total', 0)} 篇")
                print_success(f"✓ 向量数量: {final_stats.get('vectors_total', 0)} 个")
                print_success(f"✓ Neo4j 节点: {final_stats.get('neo4j_nodes', 0)} 个")
                print_success(f"✓ Neo4j 关系: {final_stats.get('neo4j_relationships', 0)} 个")
        else:
            print_error("执行过程中出现错误，请查看上面的错误信息")

        print()

    except Exception as e:
        print_error(f"执行失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

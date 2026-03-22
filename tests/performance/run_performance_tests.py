#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""
HNSW 性能测试运行脚本

此脚本用于运行 HNSW 向量索引性能测试并生成报告。
需要 PostgreSQL 数据库运行且已创建 HNSW 索引。
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# 添加 src 到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import uuid

import numpy as np
from sqlalchemy import text

from core.db.postgres import PostgresPool
from modules.storage.vector_repo import VectorRepo


class PerformanceReport:
    """性能测试报告收集器"""

    def __init__(self):
        self.results = {}

    def add_result(self, test_name: str, metrics: dict):
        """添加测试结果"""
        self.results[test_name] = metrics

    def print_report(self):
        """打印测试报告"""
        print("\n" + "=" * 80)
        print("HNSW 向量索引性能测试报告")
        print("=" * 80)

        for test_name, metrics in self.results.items():
            print(f"\n## {test_name}")
            print("-" * 80)
            for key, value in metrics.items():
                print(f"  {key}: {value}")

        print("\n" + "=" * 80)
        print("测试完成")
        print("=" * 80)


async def check_prerequisites(pool: PostgresPool):
    """检查测试前置条件"""
    print("\n检查前置条件...")

    async with pool.session() as session:
        # 检查 PostgreSQL 版本
        result = await session.execute(text("SELECT version()"))
        version = result.scalar()
        print(f"✓ PostgreSQL 版本: {version.split(',')[0]}")

        # 检查 pgvector 扩展
        result = await session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        ext_version = result.scalar_one_or_none()
        if ext_version:
            print(f"✓ pgvector 版本: {ext_version}")
        else:
            print("✗ pgvector 扩展未安装")
            return False

        # 检查 HNSW 索引
        result = await session.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'article_vectors'
              AND indexname = 'idx_article_vectors_hnsw'
        """))
        hnsw_index = result.scalar_one_or_none()

        if hnsw_index:
            print(f"✓ HNSW 索引已创建: {hnsw_index}")
        else:
            print("✗ HNSW 索引未创建，请先运行迁移: alembic upgrade head")
            return False

        return True


async def test_bulk_insert_performance(
    repo: VectorRepo, report: PerformanceReport, num_vectors: int = 1000
):
    """测试批量插入性能"""
    print(f"\n测试批量插入性能 ({num_vectors} 向量)...")

    batch_size = 500
    vector_dim = 1024

    # 生成测试数据
    all_vectors = (
        np.random.randn(num_vectors, vector_dim)
        / np.linalg.norm(np.random.randn(num_vectors, vector_dim), axis=1, keepdims=True)
    ).tolist()

    start_time = time.time()
    total_inserted = 0

    # 批量插入
    for batch_start in range(0, num_vectors, batch_size):
        batch_end = min(batch_start + batch_size, num_vectors)
        batch_vectors = all_vectors[batch_start:batch_end]

        articles = [
            (uuid.uuid4(), np.random.randn(vector_dim).tolist(), batch_vectors[i], "perf-test")
            for i in range(len(batch_vectors))
        ]

        count = await repo.bulk_upsert_article_vectors(articles)
        total_inserted += count

    total_time = time.time() - start_time
    rate = total_inserted / total_time

    print(f"✓ 插入完成: {total_inserted} 向量, {total_time:.2f}s, {rate:.1f} 向量/秒")

    report.add_result(
        "批量插入性能",
        {
            "总向量数": f"{total_inserted}",
            "总耗时": f"{total_time:.2f} 秒",
            "插入速率": f"{rate:.1f} 向量/秒",
            "性能标准": "✓ PASS" if rate >= 100 else "✗ FAIL",
        },
    )

    return rate >= 100


async def test_query_performance(
    pool: PostgresPool, repo: VectorRepo, report: PerformanceReport, num_queries: int = 20
):
    """测试查询性能"""
    print(f"\n测试查询性能 ({num_queries} 次查询)...")

    vector_dim = 1024
    query_times = []

    # 生成查询向量
    query_vectors = (
        np.random.randn(num_queries, vector_dim)
        / np.linalg.norm(np.random.randn(num_queries, vector_dim), axis=1, keepdims=True)
    ).tolist()

    for i, query_vec in enumerate(query_vectors):
        start = time.time()
        results = await repo.find_similar(
            embedding=query_vec, threshold=0.5, limit=20, model_id="perf-test"
        )
        query_time = (time.time() - start) * 1000  # ms
        query_times.append(query_time)

        if (i + 1) % 5 == 0:
            print(f"  进度: {i+1}/{num_queries}")

    avg_time = np.mean(query_times)
    max_time = np.max(query_times)
    min_time = np.min(query_times)
    std_time = np.std(query_times)

    print(f"✓ 查询完成: 平均 {avg_time:.2f}ms, 最大 {max_time:.2f}ms")

    report.add_result(
        "查询性能",
        {
            "平均时间": f"{avg_time:.2f} ms",
            "最大时间": f"{max_time:.2f} ms",
            "最小时间": f"{min_time:.2f} ms",
            "标准差": f"{std_time:.2f} ms",
            "性能标准": "✓ PASS" if max_time < 100 else "✗ FAIL",
        },
    )

    return max_time < 100


async def test_index_usage(pool: PostgresPool, report: PerformanceReport):
    """验证 HNSW 索引使用"""
    print("\n验证 HNSW 索引使用...")

    vector_dim = 1024
    query_vector = np.random.randn(vector_dim).tolist()

    async with pool.session() as session:
        result = await session.execute(
            text("""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT
                a.id::text as article_id,
                1 - (av.embedding <=> cast(:embedding as vector)) as similarity
            FROM article_vectors av
            JOIN articles a ON a.id = av.article_id
            WHERE av.vector_type = 'content'
              AND a.is_merged = FALSE
            ORDER BY similarity DESC
            LIMIT 20
        """),
            {"embedding": str(query_vector)},
        )

        plan_lines = [row[0] for row in result]

    plan_text = "\n".join(plan_lines)
    uses_hnsw = "idx_article_vectors_hnsw" in plan_text

    # 提取执行时间
    import re

    time_match = re.search(r"Execution Time: ([\d.]+) ms", plan_text)
    exec_time = float(time_match.group(1)) if time_match else 0

    status = "✓ PASS" if uses_hnsw else "✗ FAIL"
    print(f"✓ 索引使用: {status}")

    report.add_result(
        "索引使用验证",
        {
            "使用 HNSW 索引": "是" if uses_hnsw else "否",
            "执行时间": f"{exec_time:.2f} ms",
            "性能标准": status,
        },
    )

    return uses_hnsw


async def main():
    """运行所有性能测试"""
    print("=" * 80)
    print("HNSW 向量索引性能测试")
    print("=" * 80)

    # 数据库连接
    dsn = os.getenv("POSTGRES_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver")

    pool = PostgresPool(dsn)
    repo = VectorRepo(pool)

    report = PerformanceReport()

    try:
        await pool.startup()

        # 检查前置条件
        if not await check_prerequisites(pool):
            print("\n✗ 前置条件检查失败")
            return 1

        # 运行测试
        tests_passed = []

        tests_passed.append(await test_index_usage(pool, report))
        tests_passed.append(await test_bulk_insert_performance(repo, report, num_vectors=1000))
        tests_passed.append(await test_query_performance(pool, repo, report, num_queries=10))

        # 打印报告
        report.print_report()

        # 总结
        all_passed = all(tests_passed)
        if all_passed:
            print("\n✓ 所有性能测试通过")
            return 0
        else:
            print("\n✗ 部分性能测试失败")
            return 1

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        return 1

    finally:
        await pool.shutdown()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

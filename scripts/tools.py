#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified tools script for evaluation, management, and code quality checks.

Combines HNSW/BM25 evaluation, environment validation, database seeding, and logging checks.

Usage:
    # Evaluation tools
    uv run scripts/tools.py evaluate hnsw --num-vectors 1000
    uv run scripts/tools.py evaluate search --k-values 5,10,20
    uv run scripts/tools.py evaluate search --output json --output-path ./results/

    # Management tools
    uv run scripts/tools.py validate
    uv run scripts/tools.py validate --service postgres --service redis
    uv run scripts/tools.py seed
    uv run scripts/tools.py seed --reset

    # Code quality tools
    uv run scripts/tools.py check-logging
    uv run scripts/tools.py check-logging --fix-hint
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ─────────────────────────────────────────────────────────────────────────────
# Evaluation Tools (from evaluate.py)
# ─────────────────────────────────────────────────────────────────────────────


class PerformanceReport:
    """Performance test report collector for HNSW tests."""

    def __init__(self) -> None:
        self.results: dict[str, dict[str, Any]] = {}

    def add_result(self, test_name: str, metrics: dict[str, Any]) -> None:
        """Add test result."""
        self.results[test_name] = metrics

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "test_type": "hnsw_performance",
            "timestamp": datetime.now().isoformat(),
            "results": self.results,
        }

    def print_markdown(self) -> None:
        """Print report in markdown format."""
        print("\n# HNSW Vector Index Performance Test Report\n")
        print("=" * 80)

        for test_name, metrics in self.results.items():
            print(f"\n## {test_name}\n")
            print("-" * 80)
            for key, value in metrics.items():
                print(f"  **{key}**: {value}")

        print("\n" + "=" * 80)


class SearchQualityEvaluator:
    """Evaluates search quality using IR metrics."""

    def __init__(self) -> None:
        self.queries: list[dict[str, Any]] = []
        self.documents: list[Any] = []

    def load_test_data(self) -> None:
        """Load test queries and documents."""
        from modules.knowledge.search.retrievers.bm25_retriever import BM25Document

        # Define test queries with ground truth relevant documents
        self.queries = [
            {
                "query": "人工智能技术发展",
                "relevant_ids": ["doc_1", "doc_11", "doc_21"],
                "description": "AI technology development",
            },
            {
                "query": "机器学习算法",
                "relevant_ids": ["doc_2", "doc_12", "doc_22"],
                "description": "Machine learning algorithms",
            },
            {
                "query": "深度学习框架",
                "relevant_ids": ["doc_3", "doc_13", "doc_23"],
                "description": "Deep learning frameworks",
            },
            {
                "query": "自然语言处理",
                "relevant_ids": ["doc_4", "doc_14", "doc_24"],
                "description": "Natural language processing",
            },
            {
                "query": "计算机视觉应用",
                "relevant_ids": ["doc_5", "doc_15", "doc_25"],
                "description": "Computer vision applications",
            },
            {
                "query": "Python编程",
                "relevant_ids": ["doc_6", "doc_16", "doc_26"],
                "description": "Python programming",
            },
            {
                "query": "数据科学分析",
                "relevant_ids": ["doc_7", "doc_17", "doc_27"],
                "description": "Data science analysis",
            },
            {
                "query": "云原生架构",
                "relevant_ids": ["doc_8", "doc_18", "doc_28"],
                "description": "Cloud native architecture",
            },
            {
                "query": "微服务开发",
                "relevant_ids": ["doc_9", "doc_19", "doc_29"],
                "description": "Microservices development",
            },
            {
                "query": "区块链技术",
                "relevant_ids": ["doc_10", "doc_20", "doc_30"],
                "description": "Blockchain technology",
            },
        ]

        # Generate test documents
        topics = [
            ("人工智能", "技术发展迅速,深度学习和神经网络取得重大突破"),
            ("机器学习", "算法研究进展,监督学习和无监督学习应用广泛"),
            ("深度学习", "框架比较分析,TensorFlow和PyTorch各有优势"),
            ("自然语言处理", "应用案例丰富,文本分类和情感分析技术成熟"),
            ("计算机视觉", "应用领域广泛,图像识别和目标检测精度提升"),
            ("Python编程", "技术指南,Web开发和数据分析最佳实践"),
            ("数据科学", "分析方法,统计建模和机器学习结合应用"),
            ("云原生架构", "设计模式,容器化和微服务架构实践"),
            ("微服务开发", "实战经验,服务拆分和通信机制设计"),
            ("区块链技术", "原理详解,共识算法和智能合约开发"),
        ]

        for i in range(30):
            topic_idx = i % 10
            topic_name, topic_content = topics[topic_idx]
            self.documents.append(
                BM25Document(
                    doc_id=f"doc_{i + 1}",
                    title=f"{topic_name}相关文档{i + 1}",
                    content=f"这是关于{topic_name}的第{i + 1}篇文档。{topic_content}。"
                    f"本文档包含详细信息和技术要点,适合深入研究。",
                    metadata={"topic": topic_name, "index": i},
                )
            )

    def calculate_recall_at_k(
        self, retrieved_ids: list[str], relevant_ids: list[str], k: int
    ) -> float:
        """Calculate Recall@K."""
        top_k = set(retrieved_ids[:k])
        relevant = set(relevant_ids)
        if not relevant:
            return 0.0
        return len(top_k & relevant) / len(relevant)

    def calculate_precision_at_k(
        self, retrieved_ids: list[str], relevant_ids: list[str], k: int
    ) -> float:
        """Calculate Precision@K."""
        top_k = retrieved_ids[:k]
        if not top_k:
            return 0.0
        relevant = set(relevant_ids)
        return sum(1 for doc_id in top_k if doc_id in relevant) / len(top_k)

    def calculate_mrr(self, retrieved_ids: list[str], relevant_ids: list[str]) -> float:
        """Calculate Mean Reciprocal Rank."""
        relevant = set(relevant_ids)
        for rank, doc_id in enumerate(retrieved_ids, 1):
            if doc_id in relevant:
                return 1.0 / rank
        return 0.0

    def evaluate(self, retriever: Any, k_values: list[int] | None = None) -> dict[str, Any]:
        """Run full evaluation."""
        if k_values is None:
            k_values = [5, 10, 20]

        results: dict[str, Any] = {
            "test_type": "bm25_search_quality",
            "timestamp": datetime.now().isoformat(),
            "metrics": {},
            "per_query": [],
        }

        all_recall = {k: [] for k in k_values}
        all_precision = {k: [] for k in k_values}
        all_mrr = []

        for query_data in self.queries:
            query = query_data["query"]
            relevant_ids = query_data["relevant_ids"]

            # Retrieve documents
            retrieved = retriever.retrieve(query, top_k=max(k_values))
            retrieved_ids = [r.doc_id for r in retrieved]

            # Calculate metrics
            query_result: dict[str, Any] = {
                "query": query,
                "description": query_data["description"],
                "retrieved_count": len(retrieved_ids),
                "relevant_count": len(relevant_ids),
                "metrics": {},
            }

            for k in k_values:
                recall = self.calculate_recall_at_k(retrieved_ids, relevant_ids, k)
                precision = self.calculate_precision_at_k(retrieved_ids, relevant_ids, k)
                all_recall[k].append(recall)
                all_precision[k].append(precision)
                query_result["metrics"][f"recall@{k}"] = recall
                query_result["metrics"][f"precision@{k}"] = precision

            mrr = self.calculate_mrr(retrieved_ids, relevant_ids)
            all_mrr.append(mrr)
            query_result["metrics"]["mrr"] = mrr

            results["per_query"].append(query_result)

        # Calculate average metrics
        for k in k_values:
            results["metrics"][f"recall@{k}"] = sum(all_recall[k]) / len(all_recall[k])
            results["metrics"][f"precision@{k}"] = sum(all_precision[k]) / len(all_precision[k])

        results["metrics"]["mrr"] = sum(all_mrr) / len(all_mrr)
        results["metrics"]["num_queries"] = len(self.queries)

        return results

    def print_markdown(self, results: dict[str, Any]) -> None:
        """Print evaluation report in markdown format."""
        print("\n# Search Quality Evaluation Report\n")
        print("=" * 80)

        metrics = results["metrics"]
        print("\n## Overall Metrics\n")
        print("-" * 80)
        print(f"  **Number of queries**: {metrics['num_queries']}")

        # Print all available k-values dynamically
        for key in sorted(metrics.keys()):
            if key.startswith("recall@") or key.startswith("precision@"):
                print(f"  **{key}**: {metrics[key]:.4f}")

        print(f"  **MRR**: {metrics['mrr']:.4f}")

        print("\n## Per-Query Results\n")
        print("-" * 80)
        for query_result in results["per_query"]:
            print(f"\n### Query: {query_result['query']}\n")
            print(
                f"  Retrieved: {query_result['retrieved_count']}, "
                f"Relevant: {query_result['relevant_count']}"
            )
            # Print metrics dynamically
            for metric_key, value in query_result["metrics"].items():
                print(f"  **{metric_key}**: {value:.4f}")

        print("\n" + "=" * 80)


async def check_hnsw_prerequisites(pool: Any) -> bool:
    """Check HNSW test prerequisites."""
    from sqlalchemy import text

    print("\nChecking prerequisites...")

    async with pool.session() as session:
        # Check PostgreSQL version
        result = await session.execute(text("SELECT version()"))
        version = result.scalar()
        print(f"✓ PostgreSQL version: {version.split(',')[0]}")

        # Check pgvector extension
        result = await session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        ext_version = result.scalar_one_or_none()
        if ext_version:
            print(f"✓ pgvector version: {ext_version}")
        else:
            print("✗ pgvector extension not installed")
            return False

        # Check HNSW index
        result = await session.execute(text("""
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'article_vectors'
                  AND indexname = 'idx_article_vectors_hnsw'
            """))
        hnsw_index = result.scalar_one_or_none()

        if hnsw_index:
            print(f"✓ HNSW index created: {hnsw_index}")
        else:
            print("✗ HNSW index not created, run migration first: alembic upgrade head")
            return False

        return True


async def test_bulk_insert_performance(
    repo: Any, report: PerformanceReport, num_vectors: int = 1000
) -> bool:
    """Test bulk insert performance."""
    import uuid

    import numpy as np

    print(f"\nTesting bulk insert performance ({num_vectors} vectors)...")

    batch_size = 500
    vector_dim = 1024

    # Generate test data
    all_vectors = (
        np.random.randn(num_vectors, vector_dim)
        / np.linalg.norm(np.random.randn(num_vectors, vector_dim), axis=1, keepdims=True)
    ).tolist()

    start_time = time.time()
    total_inserted = 0

    # Batch insert
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

    print(f"✓ Insert complete: {total_inserted} vectors, {total_time:.2f}s, {rate:.1f} vectors/s")

    passed = rate >= 100
    report.add_result(
        "Bulk Insert Performance",
        {
            "Total vectors": f"{total_inserted}",
            "Total time": f"{total_time:.2f} s",
            "Insert rate": f"{rate:.1f} vectors/s",
            "Performance standard": "✓ PASS" if passed else "✗ FAIL",
        },
    )

    return passed


async def test_query_performance(
    pool: Any, repo: Any, report: PerformanceReport, num_queries: int = 20
) -> bool:
    """Test query performance."""
    import numpy as np

    print(f"\nTesting query performance ({num_queries} queries)...")

    vector_dim = 1024
    query_times = []

    # Generate query vectors
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
            print(f"  Progress: {i + 1}/{num_queries}")

    avg_time = np.mean(query_times)
    max_time = np.max(query_times)
    min_time = np.min(query_times)
    std_time = np.std(query_times)

    print(f"✓ Query complete: avg {avg_time:.2f}ms, max {max_time:.2f}ms")

    passed = max_time < 100
    report.add_result(
        "Query Performance",
        {
            "Average time": f"{avg_time:.2f} ms",
            "Max time": f"{max_time:.2f} ms",
            "Min time": f"{min_time:.2f} ms",
            "Std deviation": f"{std_time:.2f} ms",
            "Performance standard": "✓ PASS" if passed else "✗ FAIL",
        },
    )

    return passed


async def test_index_usage(pool: Any, report: PerformanceReport) -> bool:
    """Verify HNSW index usage."""
    import numpy as np
    from sqlalchemy import text

    print("\nVerifying HNSW index usage...")

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

    # Extract execution time
    time_match = re.search(r"Execution Time: ([\d.]+) ms", plan_text)
    exec_time = float(time_match.group(1)) if time_match else 0

    passed = uses_hnsw
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"✓ Index usage: {status}")

    report.add_result(
        "Index Usage Verification",
        {
            "Uses HNSW index": "Yes" if uses_hnsw else "No",
            "Execution time": f"{exec_time:.2f} ms",
            "Performance standard": status,
        },
    )

    return passed


async def cmd_evaluate_hnsw(args: argparse.Namespace) -> int:
    """Run HNSW performance tests."""

    from core.db.postgres import PostgresPool
    from modules.storage.vector_repo import VectorRepo

    print("=" * 80)
    print("HNSW Vector Index Performance Test")
    print("=" * 80)

    # Database connection
    dsn = os.getenv("POSTGRES_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver")

    pool = PostgresPool(dsn)
    repo = VectorRepo(pool)

    report = PerformanceReport()

    try:
        await pool.startup()

        # Check prerequisites
        if not await check_hnsw_prerequisites(pool):
            print("\n✗ Prerequisites check failed")
            return 1

        # Run tests
        tests_passed = []

        tests_passed.append(await test_index_usage(pool, report))
        tests_passed.append(await test_bulk_insert_performance(repo, report, args.num_vectors))
        tests_passed.append(await test_query_performance(pool, repo, report, args.num_queries))

        # Print report
        if args.output == "json":
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            report.print_markdown()

        # Summary
        all_passed = all(tests_passed)
        if all_passed:
            print("\n✓ All performance tests passed")
            return 0
        else:
            print("\n✗ Some performance tests failed")
            return 1

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    finally:
        await pool.shutdown()


def cmd_evaluate_search(args: argparse.Namespace) -> int:
    """Run BM25 search quality tests."""
    from modules.knowledge.search.retrievers.bm25_retriever import BM25Retriever

    print("=" * 80)
    print("Search Quality Evaluation")
    print("=" * 80)

    # Initialize evaluator
    evaluator = SearchQualityEvaluator()

    # Load test data
    print("\nLoading test data...")
    evaluator.load_test_data()
    print(f"  Loaded {len(evaluator.queries)} queries")
    print(f"  Loaded {len(evaluator.documents)} documents")

    # Initialize BM25 retriever
    print("\nInitializing BM25 retriever...")
    retriever = BM25Retriever(language="zh")
    retriever.index(evaluator.documents)
    print(f"  Indexed {retriever.get_document_count()} documents")

    # Run evaluation
    print("\nRunning evaluation...")
    results = evaluator.evaluate(retriever, k_values=args.k_values)

    # Print report
    if args.output == "json":
        output_json = json.dumps(results, ensure_ascii=False, indent=2)
        print(output_json)
    else:
        evaluator.print_markdown(results)

    # Save results if output path specified
    if args.output_path:
        output_dir = Path(args.output_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"search_quality_{timestamp}.json"
        file_path = output_dir / filename
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nResults saved to: {file_path}")

    return 0


def parse_k_values(value: str) -> list[int]:
    """Parse k-values from comma-separated string."""
    return [int(k.strip()) for k in value.split(",")]


# ─────────────────────────────────────────────────────────────────────────────
# Management Tools (from manage.py)
# ─────────────────────────────────────────────────────────────────────────────


# Seed Data
RELATION_TYPES: list[dict] = [
    # --- 组织 ---
    {
        "name": "任职于",
        "name_en": "WORKS_AT",
        "category": "组织",
        "is_symmetric": False,
        "sort_order": 1,
        "description": "某人在某组织担任职务",
        "aliases": ["就职于", "工作于", "供职于", "担任", "就职"],
    },
    {
        "name": "隶属于",
        "name_en": "AFFILIATED_WITH",
        "category": "组织",
        "is_symmetric": False,
        "sort_order": 2,
        "description": "某组织隶属于另一组织",
        "aliases": ["隶属", "下属", "从属", "归属", "所属"],
    },
    {
        "name": "控股",
        "name_en": "CONTROLS",
        "category": "组织",
        "is_symmetric": False,
        "sort_order": 3,
        "description": "某组织控股另一组织",
        "aliases": ["控制", "控股关系", "持股", "持有", "掌控", "实际控制"],
    },
    # --- 空间 ---
    {
        "name": "位于",
        "name_en": "LOCATED_IN",
        "category": "空间",
        "is_symmetric": False,
        "sort_order": 4,
        "description": "某实体位于某地理位置",
        "aliases": ["地处", "坐落于", "在", "驻地", "所在地"],
    },
    # --- 商业 ---
    {
        "name": "收购",
        "name_en": "ACQUIRES",
        "category": "商业",
        "is_symmetric": False,
        "sort_order": 5,
        "description": "某实体收购另一实体",
        "aliases": ["并购", "收购了", "吞并", "买下", "收购案"],
    },
    {
        "name": "供应",
        "name_en": "SUPPLIES",
        "category": "商业",
        "is_symmetric": False,
        "sort_order": 6,
        "description": "某实体向另一实体提供产品或服务",
        "aliases": ["提供", "供应商", "供货", "供给", "供应了"],
    },
    {
        "name": "投资",
        "name_en": "INVESTS_IN",
        "category": "商业",
        "is_symmetric": False,
        "sort_order": 7,
        "description": "某实体投资另一实体",
        "aliases": ["注资", "投资了", "融资", "领投", "参投", "入股"],
    },
    {
        "name": "合作",
        "name_en": "PARTNERS_WITH",
        "category": "商业",
        "is_symmetric": True,
        "sort_order": 8,
        "description": "实体之间的合作关系",
        "aliases": ["战略合作", "联合", "合作开发", "协作", "携手", "结盟", "联名"],
    },
    {
        "name": "竞争",
        "name_en": "COMPETES_WITH",
        "category": "商业",
        "is_symmetric": True,
        "sort_order": 9,
        "description": "实体之间的竞争关系",
        "aliases": ["对抗", "竞品", "竞争关系", "对手", "对峙", "相争"],
    },
    # --- 行为 ---
    {
        "name": "发布",
        "name_en": "PUBLISHES",
        "category": "行为",
        "is_symmetric": False,
        "sort_order": 10,
        "description": "某实体发布某内容或产品",
        "aliases": ["公布", "宣布", "发表", "推出", "公布于", "对外发布"],
    },
    {
        "name": "签署",
        "name_en": "SIGNS",
        "category": "行为",
        "is_symmetric": False,
        "sort_order": 11,
        "description": "某实体签署某协议或文件",
        "aliases": ["签订", "签约", "缔结", "达成", "签署了", "签订协议"],
    },
    {
        "name": "参与",
        "name_en": "PARTICIPATES_IN",
        "category": "行为",
        "is_symmetric": False,
        "sort_order": 12,
        "description": "某实体参与某事件或活动",
        "aliases": ["加入", "参加了", "介入", "出席", "参与活动"],
    },
    # --- 权力 ---
    {
        "name": "监管",
        "name_en": "REGULATES",
        "category": "权力",
        "is_symmetric": False,
        "sort_order": 13,
        "description": "某实体监管另一实体",
        "aliases": ["监管关系", "监督", "管理", "管辖", "监察", "督导"],
    },
    {
        "name": "支持",
        "name_en": "SUPPORTS",
        "category": "权力",
        "is_symmetric": False,
        "sort_order": 14,
        "description": "某实体支持另一实体",
        "aliases": ["援助", "资助", "扶持", "力挺", "背书", "支持了"],
    },
    {
        "name": "制裁",
        "name_en": "SANCTIONS",
        "category": "权力",
        "is_symmetric": False,
        "sort_order": 15,
        "description": "某实体对另一实体实施制裁",
        "aliases": ["惩罚", "封禁", "处罚", "禁运", "制裁了", "限制"],
    },
    # --- 因果 ---
    {
        "name": "引发",
        "name_en": "CAUSES",
        "category": "因果",
        "is_symmetric": False,
        "sort_order": 16,
        "description": "某事件引发另一事件",
        "aliases": ["导致", "触发", "造成", "引起", "引发了", "催生"],
    },
    {
        "name": "影响",
        "name_en": "INFLUENCES",
        "category": "因果",
        "is_symmetric": False,
        "sort_order": 17,
        "description": "某实体影响另一实体",
        "aliases": ["左右", "波及", "影响了", "作用于", "传导"],
    },
]


async def cmd_validate(args: argparse.Namespace) -> int:
    """Run environment validation."""
    from config.settings import Settings
    from core.health.env_validator import EnvironmentValidator

    try:
        settings = Settings()
    except Exception as exc:
        print(f"\033[91mFailed to load settings:\033[0m {exc}")
        return 1

    validator = EnvironmentValidator(settings)
    results = await validator.validate_all(args.service)
    validator.print_report(results)

    return validator.get_exit_code(results)


async def cmd_seed(args: argparse.Namespace) -> int:
    """Seed relation types and aliases into the database."""
    from sqlalchemy import delete, func, select

    from config.settings import Settings
    from core.db.models import RelationType, RelationTypeAlias
    from core.db.postgres import PostgresPool

    try:
        settings = Settings()
    except Exception as exc:
        print(f"\033[91mFailed to load settings:\033[0m {exc}")
        return 1

    pool = PostgresPool(settings.postgres.dsn)

    try:
        await pool.startup()

        async with pool.session() as session:
            if args.reset:
                await session.execute(delete(RelationTypeAlias))
                await session.execute(delete(RelationType))
                await session.flush()
                print("Cleared all relation types data")

            # Count existing
            existing_count = await session.scalar(select(func.count()).select_from(RelationType))
            print(f"Existing relation types in database: {existing_count}")

            inserted_types = 0
            skipped_types = 0
            inserted_aliases = 0

            for rt_data in RELATION_TYPES:
                aliases = rt_data.pop("aliases")

                # Check if type already exists (by name_en)
                existing = await session.scalar(
                    select(RelationType).where(RelationType.name_en == rt_data["name_en"])
                )

                if existing:
                    skipped_types += 1
                    type_id = existing.id
                    print(f"  Skipped (exists): {rt_data['name']} ({rt_data['name_en']})")
                else:
                    rt = RelationType(**rt_data, is_active=True)
                    session.add(rt)
                    await session.flush()
                    type_id = rt.id
                    inserted_types += 1
                    print(f"  Inserted: {rt_data['name']} ({rt_data['name_en']})")

                # Insert missing aliases
                for alias_str in aliases:
                    existing_alias = await session.scalar(
                        select(RelationTypeAlias).where(
                            RelationTypeAlias.relation_type_id == type_id,
                            RelationTypeAlias.alias == alias_str,
                        )
                    )
                    if not existing_alias:
                        session.add(RelationTypeAlias(alias=alias_str, relation_type_id=type_id))
                        inserted_aliases += 1

            await session.commit()

        print(
            f"\nDone: inserted {inserted_types} types, skipped {skipped_types}, "
            f"inserted {inserted_aliases} aliases"
        )
        return 0

    except Exception as exc:
        print(f"\033[91mSeed failed:\033[0m {exc}")
        import traceback

        traceback.print_exc()
        return 1

    finally:
        await pool.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# Code Quality Tools (from check_logging_usage.py)
# ─────────────────────────────────────────────────────────────────────────────


# Patterns that indicate prohibited logging usage
PROHIBITED_PATTERNS = [
    (
        r"logging\.getLogger\s*\(",
        "logging.getLogger() - use get_logger() from core.observability.logging",
    ),
    (
        r"logging\.(debug|info|warning|error|critical|exception)\s*\(",
        "logging.{level}() - use loguru's log.{level}() instead",
    ),
    (r"logging\.basicConfig\s*\(", "logging.basicConfig() - use loguru configuration instead"),
    (
        r"logging\.(FileHandler|StreamHandler|Handler)\s*\(",
        "logging handlers - use loguru's file output instead",
    ),
]

# Files/patterns to exclude from checking
EXCLUDE_PATTERNS = [
    r"__pycache__",
    r"\.venv",
    r"venv",
    r"\.git",
    r"site-packages",
    r"check_logging_usage\.py$",
    r"logging\.py$",
    r"scripts/tools\.py$",
]


def should_check_file(file_path: Path) -> bool:
    """Check if a file should be scanned."""
    file_str = str(file_path)

    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, file_str):
            return False

    return file_path.suffix == ".py"


def check_file(file_path: Path) -> list[tuple[int, str, str]]:
    """Check a single file for prohibited logging usage."""
    violations = []

    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        for i, line in enumerate(lines, start=1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # Check each prohibited pattern
            for pattern, message in PROHIBITED_PATTERNS:
                if re.search(pattern, line):
                    violations.append((i, line.strip(), message))
                    break  # Only report one violation per line

    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)

    return violations


def cmd_check_logging(args: argparse.Namespace) -> int:
    """Check for prohibited logging module usage."""
    # Determine paths to check
    if args.files:
        paths = [Path(f) for f in args.files]
    else:
        paths = [Path("src"), Path("tests"), Path("scripts")]

    # Collect all Python files
    all_files = []
    for path in paths:
        if path.is_file():
            if should_check_file(path):
                all_files.append(path)
        elif path.is_dir():
            for py_file in path.rglob("*.py"):
                if should_check_file(py_file):
                    all_files.append(py_file)

    # Check all files
    total_violations = 0
    for file_path in all_files:
        violations = check_file(file_path)

        if violations:
            total_violations += len(violations)
            print(f"\n❌ {file_path}")

            for line_num, line_content, message in violations:
                print(f"  Line {line_num}: {message}")
                print(f"    {line_content}")

                if args.fix_hint:
                    print(f"    → Replace with: from core.observability.logging import get_logger")
                    print(f"    → Then use: log = get_logger(__name__)")

    # Summary
    if total_violations > 0:
        print(f"\n❌ Found {total_violations} logging violation(s) in {len(all_files)} files")
        print("\n💡 Fix: Use loguru instead of logging module")
        print("   from core.observability.logging import get_logger")
        print("   log = get_logger(__name__)")
        return 1

    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Monitoring Tools
# ─────────────────────────────────────────────────────────────────────────────


async def cmd_monitor(args: argparse.Namespace) -> int:
    """Run database monitoring checks.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    from sqlalchemy import text

    from container import Container

    if args.check_indexes:
        print("\n🔍 Checking for unused database indexes...")

        container = Container().configure()
        pool = container.relational_pool()

        if container.relational_pool_type != "postgres":
            print("⚠️  Index monitoring only available for PostgreSQL")
            return 0

        async with pool.session() as session:
            result = await session.execute(
                text("""
                    SELECT
                        schemaname || '.' || relname AS table,
                        indexrelname AS index,
                        idx_scan AS scans,
                        pg_size_pretty(pg_relation_size(indexrelid)) AS size
                    FROM pg_stat_user_indexes
                    WHERE idx_scan < :threshold
                    ORDER BY idx_scan ASC
                """),
                {"threshold": args.threshold},
            )

            unused = [dict(row._mapping) for row in result]

            if unused:
                print(
                    f"\n⚠️  Found {len(unused)} potentially unused indexes (scans < {args.threshold}):"
                )
                for idx in unused:
                    print(
                        f"  - {idx['table']}.{idx['index']} (scans: {idx['scans']}, size: {idx['size']})"
                    )
                print(
                    f"\n💡 Consider removing these indexes to save disk space and improve write performance."
                )
            else:
                print(f"\n✅ All indexes are being used effectively (scans >= {args.threshold})")

        return 0

    # Default: print help
    print("Usage:")
    print("  uv run scripts/tools.py monitor --check-indexes")
    print("  uv run scripts/tools.py monitor --check-indexes --threshold 20")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Unified tools script for evaluation, management, and code quality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Evaluation tools
    uv run scripts/tools.py evaluate hnsw --num-vectors 1000
    uv run scripts/tools.py evaluate search --k-values 5,10,20

    # Management tools
    uv run scripts/tools.py validate
    uv run scripts/tools.py validate --service postgres
    uv run scripts/tools.py seed --reset

    # Code quality tools
    uv run scripts/tools.py check-logging
    uv run scripts/tools.py check-logging --fix-hint
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Evaluate subcommand
    eval_parser = subparsers.add_parser("evaluate", help="Run performance and quality evaluations")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_type", help="Evaluation type")

    # HNSW evaluation
    hnsw_parser = eval_subparsers.add_parser("hnsw", help="Run HNSW vector index performance tests")
    hnsw_parser.add_argument(
        "--num-vectors",
        type=int,
        default=1000,
        help="Number of vectors for bulk insert test (default: 1000)",
    )
    hnsw_parser.add_argument(
        "--num-queries",
        type=int,
        default=20,
        help="Number of queries for query performance test (default: 20)",
    )
    hnsw_parser.add_argument(
        "--output",
        choices=["json", "markdown"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    # Search evaluation
    search_parser = eval_subparsers.add_parser("search", help="Run BM25 search quality evaluation")
    search_parser.add_argument(
        "--k-values",
        type=parse_k_values,
        default=[5, 10, 20],
        help="K values for Recall@K and Precision@K metrics (comma-separated, default: 5,10,20)",
    )
    search_parser.add_argument(
        "--output",
        choices=["json", "markdown"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    search_parser.add_argument(
        "--output-path",
        type=str,
        default=None,
        help="Directory path to save results (default: none, print to stdout)",
    )

    # Validate subcommand
    validate_parser = subparsers.add_parser(
        "validate", help="Validate environment services (PostgreSQL, Neo4j, Redis, LLM, Embedding)"
    )
    validate_parser.add_argument(
        "--service",
        action="append",
        choices=["postgres", "neo4j", "redis", "llm", "embedding"],
        help="Service to validate (can be specified multiple times)",
    )

    # Seed subcommand
    seed_parser = subparsers.add_parser(
        "seed", help="Seed relation types and aliases into the database"
    )
    seed_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all existing types and re-insert",
    )

    # Check-logging subcommand
    check_logging_parser = subparsers.add_parser(
        "check-logging", help="Check for prohibited logging module usage"
    )
    check_logging_parser.add_argument(
        "files",
        nargs="*",
        help="Files or directories to check (default: src/ tests/ scripts/)",
    )
    check_logging_parser.add_argument(
        "--fix-hint",
        action="store_true",
        help="Print fix hints for violations",
    )

    # Monitor subcommand
    monitor_parser = subparsers.add_parser(
        "monitor", help="Database performance monitoring and index analysis"
    )
    monitor_parser.add_argument(
        "--check-indexes",
        action="store_true",
        help="Check for unused database indexes",
    )
    monitor_parser.add_argument(
        "--threshold",
        type=int,
        default=10,
        help="Minimum index scan count to consider used (default: 10)",
    )

    args = parser.parse_args()

    if args.command == "evaluate":
        if args.eval_type == "hnsw":
            return asyncio.run(cmd_evaluate_hnsw(args))
        elif args.eval_type == "search":
            return cmd_evaluate_search(args)
        else:
            eval_parser.print_help()
            return 1
    elif args.command == "validate":
        return asyncio.run(cmd_validate(args))
    elif args.command == "seed":
        return asyncio.run(cmd_seed(args))
    elif args.command == "check-logging":
        return cmd_check_logging(args)
    elif args.command == "monitor":
        return asyncio.run(cmd_monitor(args))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

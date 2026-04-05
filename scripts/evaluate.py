#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""
Unified Evaluation Script

Combines HNSW vector index performance tests and BM25 search quality evaluation.

Usage:
    python scripts/evaluate.py hnsw --num-vectors 1000
    python scripts/evaluate.py search --k-values 5,10,20
    python scripts/evaluate.py search --output json --output-path ./results/
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

import uuid

import numpy as np
from sqlalchemy import text

from core.db.postgres import PostgresPool
from modules.knowledge.search.retrievers.bm25_retriever import BM25Document, BM25Retriever
from modules.storage.vector_repo import VectorRepo


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
        self.documents: list[BM25Document] = []

    def load_test_data(self) -> None:
        """Load test queries and documents."""
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
            ("人工智能", "技术发展迅速，深度学习和神经网络取得重大突破"),
            ("机器学习", "算法研究进展，监督学习和无监督学习应用广泛"),
            ("深度学习", "框架比较分析，TensorFlow和PyTorch各有优势"),
            ("自然语言处理", "应用案例丰富，文本分类和情感分析技术成熟"),
            ("计算机视觉", "应用领域广泛，图像识别和目标检测精度提升"),
            ("Python编程", "技术指南，Web开发和数据分析最佳实践"),
            ("数据科学", "分析方法，统计建模和机器学习结合应用"),
            ("云原生架构", "设计模式，容器化和微服务架构实践"),
            ("微服务开发", "实战经验，服务拆分和通信机制设计"),
            ("区块链技术", "原理详解，共识算法和智能合约开发"),
        ]

        for i in range(30):
            topic_idx = i % 10
            topic_name, topic_content = topics[topic_idx]
            self.documents.append(
                BM25Document(
                    doc_id=f"doc_{i + 1}",
                    title=f"{topic_name}相关文档{i + 1}",
                    content=f"这是关于{topic_name}的第{i + 1}篇文档。{topic_content}。"
                    f"本文档包含详细信息和技术要点，适合深入研究。",
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

    def evaluate(
        self, retriever: BM25Retriever, k_values: list[int] | None = None
    ) -> dict[str, Any]:
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


async def check_hnsw_prerequisites(pool: PostgresPool) -> bool:
    """Check HNSW test prerequisites."""
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
    repo: VectorRepo, report: PerformanceReport, num_vectors: int = 1000
) -> bool:
    """Test bulk insert performance."""
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
    pool: PostgresPool, repo: VectorRepo, report: PerformanceReport, num_queries: int = 20
) -> bool:
    """Test query performance."""
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


async def test_index_usage(pool: PostgresPool, report: PerformanceReport) -> bool:
    """Verify HNSW index usage."""
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


async def run_hnsw_tests(
    num_vectors: int = 1000, num_queries: int = 20, output_format: str = "markdown"
) -> int:
    """Run HNSW performance tests."""
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
        tests_passed.append(await test_bulk_insert_performance(repo, report, num_vectors))
        tests_passed.append(await test_query_performance(pool, repo, num_queries))

        # Print report
        if output_format == "json":
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


def run_search_tests(
    k_values: list[int] | None = None,
    output_format: str = "markdown",
    output_path: str | None = None,
) -> int:
    """Run BM25 search quality tests."""
    print("=" * 80)
    print("Search Quality Evaluation")
    print("=" * 80)

    if k_values is None:
        k_values = [5, 10, 20]

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
    results = evaluator.evaluate(retriever, k_values=k_values)

    # Print report
    if output_format == "json":
        output_json = json.dumps(results, ensure_ascii=False, indent=2)
        print(output_json)
    else:
        evaluator.print_markdown(results)

    # Save results if output path specified
    if output_path:
        output_dir = Path(output_path)
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


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Unified evaluation script for HNSW performance and BM25 search quality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # HNSW subcommand
    hnsw_parser = subparsers.add_parser("hnsw", help="Run HNSW vector index performance tests")
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

    # Search subcommand
    search_parser = subparsers.add_parser("search", help="Run BM25 search quality evaluation")
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

    args = parser.parse_args()

    if args.subcommand == "hnsw":
        return asyncio.run(
            run_hnsw_tests(
                num_vectors=args.num_vectors,
                num_queries=args.num_queries,
                output_format=args.output,
            )
        )
    elif args.subcommand == "search":
        return run_search_tests(
            k_values=args.k_values,
            output_format=args.output,
            output_path=args.output_path,
        )
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

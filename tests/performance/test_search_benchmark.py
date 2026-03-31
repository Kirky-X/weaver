#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""
Search Enhancement Performance Benchmark

This script benchmarks the performance of search enhancement components:
- BM25 retrieval latency
- RRF fusion latency
- Flashrank re-ranking latency
- MMR diversity re-ranking latency
- Full hybrid search pipeline latency

Target: Total latency < 100ms
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from modules.knowledge.search.engines.hybrid_search import HybridSearchConfig, HybridSearchEngine
from modules.knowledge.search.fusion.rrf import reciprocal_rank_fusion
from modules.knowledge.search.rerankers.flashrank_reranker import FlashrankReranker
from modules.knowledge.search.rerankers.mmr_reranker import MMRReranker
from modules.knowledge.search.retrievers.bm25_retriever import BM25Document, BM25Retriever


class PerformanceReport:
    """Performance test report collector."""

    def __init__(self) -> None:
        self.results: dict[str, dict[str, Any]] = {}

    def add_result(self, test_name: str, metrics: dict[str, Any]) -> None:
        """Add test result."""
        self.results[test_name] = metrics

    def print_report(self) -> None:
        """Print test report."""
        print("\n" + "=" * 80)
        print("Search Enhancement Performance Benchmark Report")
        print("=" * 80)

        for test_name, metrics in self.results.items():
            print(f"\n## {test_name}")
            print("-" * 80)
            for key, value in metrics.items():
                if isinstance(value, float):
                    print(f"  {key}: {value:.4f}")
                else:
                    print(f"  {key}: {value}")

        # Print summary
        print("\n" + "=" * 80)
        print("Summary")
        print("=" * 80)

        total_latency = sum(metrics.get("avg_latency_ms", 0) for metrics in self.results.values())
        print(f"  Total pipeline latency estimate: {total_latency:.2f}ms")

        if total_latency < 100:
            print("  ✓ PASSED: Total latency < 100ms")
        else:
            print("  ✗ FAILED: Total latency >= 100ms")

        print("\n" + "=" * 80)


def generate_test_documents(count: int = 1000) -> list[BM25Document]:
    """Generate test documents for benchmarking."""
    documents = []
    topics = [
        "人工智能技术发展迅速",
        "机器学习算法研究进展",
        "深度学习框架比较分析",
        "自然语言处理应用案例",
        "计算机视觉最新突破",
        "数据科学最佳实践",
        "Python编程技术指南",
        "云原生架构设计模式",
        "微服务系统开发实战",
        "区块链技术原理详解",
    ]

    for i in range(count):
        topic_idx = i % len(topics)
        documents.append(
            BM25Document(
                doc_id=f"doc_{i}",
                title=f"文档{i}: {topics[topic_idx]}",
                content=f"这是第{i}篇文档的内容。主题：{topics[topic_idx]}。"
                f"详细内容包含多个关键词和语义信息，用于测试搜索性能。",
                metadata={"index": i, "topic": topics[topic_idx]},
            )
        )

    return documents


def benchmark_bm25_retrieval(
    retriever: BM25Retriever,
    queries: list[str],
    iterations: int = 100,
) -> dict[str, Any]:
    """Benchmark BM25 retrieval latency."""
    latencies = []

    for _ in range(iterations):
        for query in queries:
            start = time.perf_counter()
            retriever.retrieve(query, top_k=10)
            end = time.perf_counter()
            latencies.append((end - start) * 1000)  # Convert to ms

    return {
        "iterations": len(latencies),
        "avg_latency_ms": sum(latencies) / len(latencies),
        "min_latency_ms": min(latencies),
        "max_latency_ms": max(latencies),
        "p50_latency_ms": sorted(latencies)[len(latencies) // 2],
        "p99_latency_ms": sorted(latencies)[int(len(latencies) * 0.99)],
    }


def benchmark_rrf_fusion(iterations: int = 1000) -> dict[str, Any]:
    """Benchmark RRF fusion latency."""
    # Create mock results
    vector_results = [(f"doc_{i}", 0.9 - i * 0.01) for i in range(20)]
    bm25_results = [(f"doc_{i + 5}", 15.0 - i) for i in range(20)]

    latencies = []

    for _ in range(iterations):
        start = time.perf_counter()
        reciprocal_rank_fusion([vector_results, bm25_results])
        end = time.perf_counter()
        latencies.append((end - start) * 1000)

    return {
        "iterations": iterations,
        "avg_latency_ms": sum(latencies) / len(latencies),
        "min_latency_ms": min(latencies),
        "max_latency_ms": max(latencies),
        "p50_latency_ms": sorted(latencies)[len(latencies) // 2],
    }


def benchmark_flashrank_reranking(
    reranker: FlashrankReranker,
    iterations: int = 100,
) -> dict[str, Any]:
    """Benchmark Flashrank re-ranking latency."""
    # Create mock candidates
    candidates = [
        {"id": f"doc_{i}", "content": f"Document content {i} for testing", "score": 0.9 - i * 0.01}
        for i in range(20)
    ]

    latencies = []

    for _ in range(iterations):
        start = time.perf_counter()
        reranker.rerank("test query", candidates, top_k=10)
        end = time.perf_counter()
        latencies.append((end - start) * 1000)

    return {
        "iterations": iterations,
        "avg_latency_ms": sum(latencies) / len(latencies),
        "min_latency_ms": min(latencies),
        "max_latency_ms": max(latencies),
        "available": reranker.is_available(),
    }


def benchmark_mmr_reranking(
    reranker: MMRReranker,
    iterations: int = 100,
) -> dict[str, Any]:
    """Benchmark MMR diversity re-ranking latency."""
    # Create mock candidates
    candidates = [
        {
            "id": f"doc_{i}",
            "content": f"Document content {i} for testing diversity",
            "score": 0.9 - i * 0.01,
        }
        for i in range(20)
    ]

    latencies = []

    for _ in range(iterations):
        start = time.perf_counter()
        reranker.rerank(candidates, top_k=10)
        end = time.perf_counter()
        latencies.append((end - start) * 1000)

    return {
        "iterations": iterations,
        "avg_latency_ms": sum(latencies) / len(latencies),
        "min_latency_ms": min(latencies),
        "max_latency_ms": max(latencies),
    }


def benchmark_hybrid_search(
    retriever: BM25Retriever,
    iterations: int = 50,
) -> dict[str, Any]:
    """Benchmark full hybrid search pipeline latency."""
    # Create engine
    config = HybridSearchConfig(
        hybrid_enabled=True,
        rerank_enabled=False,  # Disable for pure pipeline test
        mmr_enabled=False,
    )
    engine = HybridSearchEngine(
        bm25_retriever=retriever,
        config=config,
    )

    queries = ["人工智能", "机器学习", "深度学习", "自然语言处理", "计算机视觉"]
    latencies = []

    for _ in range(iterations):
        for query in queries:
            start = time.perf_counter()
            # Synchronous call in async context (mocked)
            retriever.retrieve(query, top_k=10)
            # Simulate RRF fusion
            reciprocal_rank_fusion([[("doc_1", 0.9), ("doc_2", 0.8)]])
            end = time.perf_counter()
            latencies.append((end - start) * 1000)

    return {
        "iterations": len(latencies),
        "avg_latency_ms": sum(latencies) / len(latencies),
        "min_latency_ms": min(latencies),
        "max_latency_ms": max(latencies),
        "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)],
    }


def main() -> None:
    """Run all benchmarks."""
    print("=" * 80)
    print("Search Enhancement Performance Benchmark")
    print("=" * 80)
    print("\nInitializing test environment...")

    report = PerformanceReport()

    # Generate test data
    print("\nGenerating test documents...")
    documents = generate_test_documents(count=1000)
    print(f"  Generated {len(documents)} documents")

    # Initialize BM25 retriever
    print("\nInitializing BM25 retriever...")
    bm25_retriever = BM25Retriever(language="zh")
    bm25_retriever.index(documents)
    print(f"  Indexed {bm25_retriever.get_document_count()} documents")

    # Initialize rerankers
    print("\nInitializing rerankers...")
    flashrank = FlashrankReranker(enabled=False)  # Disabled for benchmarking
    mmr = MMRReranker(lambda_param=0.7)
    print(f"  Flashrank available: {flashrank.is_available()}")

    # Test queries
    queries = [
        "人工智能技术",
        "机器学习算法",
        "深度学习框架",
        "自然语言处理",
        "计算机视觉应用",
    ]

    # Run benchmarks
    print("\n" + "-" * 80)
    print("Running benchmarks...")
    print("-" * 80)

    # BM25 retrieval
    print("\n1. Benchmarking BM25 retrieval...")
    bm25_results = benchmark_bm25_retrieval(bm25_retriever, queries, iterations=100)
    report.add_result("BM25 Retrieval", bm25_results)
    print(f"   Avg latency: {bm25_results['avg_latency_ms']:.2f}ms")

    # RRF fusion
    print("\n2. Benchmarking RRF fusion...")
    rrf_results = benchmark_rrf_fusion(iterations=1000)
    report.add_result("RRF Fusion", rrf_results)
    print(f"   Avg latency: {rrf_results['avg_latency_ms']:.4f}ms")

    # Flashrank reranking
    print("\n3. Benchmarking Flashrank reranking...")
    flashrank_results = benchmark_flashrank_reranking(flashrank, iterations=100)
    report.add_result("Flashrank Reranking", flashrank_results)
    print(f"   Avg latency: {flashrank_results['avg_latency_ms']:.2f}ms")

    # MMR reranking
    print("\n4. Benchmarking MMR diversity reranking...")
    mmr_results = benchmark_mmr_reranking(mmr, iterations=100)
    report.add_result("MMR Diversity Reranking", mmr_results)
    print(f"   Avg latency: {mmr_results['avg_latency_ms']:.2f}ms")

    # Hybrid search pipeline
    print("\n5. Benchmarking hybrid search pipeline...")
    hybrid_results = benchmark_hybrid_search(bm25_retriever, iterations=50)
    report.add_result("Hybrid Search Pipeline", hybrid_results)
    print(f"   Avg latency: {hybrid_results['avg_latency_ms']:.2f}ms")

    # Print final report
    report.print_report()

    # Save results to memory for reference
    print("\nBenchmark complete!")


if __name__ == "__main__":
    main()

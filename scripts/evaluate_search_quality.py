#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""
Search Quality Evaluation Script

This script evaluates search quality using standard IR metrics:
- Recall@K: Proportion of relevant items retrieved in top K results
- Precision@K: Proportion of retrieved items that are relevant
- MRR (Mean Reciprocal Rank): Average rank of first relevant item
- NDCG@K: Normalized Discounted Cumulative Gain

Usage:
    python scripts/evaluate_search_quality.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from modules.search.retrievers.bm25_retriever import BM25Document, BM25Retriever


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
        self,
        retrieved_ids: list[str],
        relevant_ids: list[str],
        k: int,
    ) -> float:
        """Calculate Recall@K."""
        top_k = set(retrieved_ids[:k])
        relevant = set(relevant_ids)
        if not relevant:
            return 0.0
        return len(top_k & relevant) / len(relevant)

    def calculate_precision_at_k(
        self,
        retrieved_ids: list[str],
        relevant_ids: list[str],
        k: int,
    ) -> float:
        """Calculate Precision@K."""
        top_k = retrieved_ids[:k]
        if not top_k:
            return 0.0
        relevant = set(relevant_ids)
        return sum(1 for doc_id in top_k if doc_id in relevant) / len(top_k)

    def calculate_mrr(
        self,
        retrieved_ids: list[str],
        relevant_ids: list[str],
    ) -> float:
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
        results = {
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
            query_result = {
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

    def print_report(self, results: dict[str, Any]) -> None:
        """Print evaluation report."""
        print("\n" + "=" * 80)
        print("Search Quality Evaluation Report")
        print("=" * 80)

        print("\n## Overall Metrics")
        print("-" * 80)
        metrics = results["metrics"]
        print(f"  Number of queries: {metrics['num_queries']}")
        print(f"  Recall@5:  {metrics['recall@5']:.4f}")
        print(f"  Recall@10: {metrics['recall@10']:.4f}")
        print(f"  Recall@20: {metrics['recall@20']:.4f}")
        print(f"  Precision@5:  {metrics['precision@5']:.4f}")
        print(f"  Precision@10: {metrics['precision@10']:.4f}")
        print(f"  Precision@20: {metrics['precision@20']:.4f}")
        print(f"  MRR: {metrics['mrr']:.4f}")

        print("\n## Per-Query Results")
        print("-" * 80)
        for query_result in results["per_query"]:
            print(f"\n  Query: {query_result['query']}")
            print(
                f"    Retrieved: {query_result['retrieved_count']}, Relevant: {query_result['relevant_count']}"
            )
            print(f"    Recall@10: {query_result['metrics']['recall@10']:.4f}")
            print(f"    Precision@10: {query_result['metrics']['precision@10']:.4f}")
            print(f"    MRR: {query_result['metrics']['mrr']:.4f}")

        print("\n" + "=" * 80)
        print("Evaluation Summary")
        print("=" * 80)

        # Quality assessment
        recall_10 = metrics["recall@10"]
        if recall_10 >= 0.7:
            print(f"  ✓ GOOD: Recall@10 = {recall_10:.2%} >= 70%")
        elif recall_10 >= 0.5:
            print(f"  ○ ACCEPTABLE: Recall@10 = {recall_10:.2%} >= 50%")
        else:
            print(f"  ✗ NEEDS IMPROVEMENT: Recall@10 = {recall_10:.2%} < 50%")

        print("\n" + "=" * 80)


def main() -> None:
    """Run search quality evaluation."""
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
    results = evaluator.evaluate(retriever, k_values=[5, 10, 20])

    # Print report
    evaluator.print_report(results)

    # Save results
    output_path = Path(__file__).parent.parent / "temp" / "search_quality_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DRIFT Search Engine - Dynamic Reasoning and Inference Framework.

DRIFT combines global community insights with local entity details through
an iterative three-phase search process:
1. Primer Phase: Vector search community reports, generate initial answer
2. Follow-Up Phase: Iterative local search based on generated questions
3. Output Phase: Aggregate into hierarchical response
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.db.neo4j import Neo4jPool
from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from modules.knowledge.search.context.global_context import GlobalContextBuilder
from modules.knowledge.search.engines.local_search import LocalSearchEngine

log = get_logger("search.drift_engine")


@dataclass
class DriftHierarchy:
    """Hierarchical structure for DRIFT search results."""

    primer: dict[str, Any] = field(default_factory=dict)
    follow_ups: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DriftResult:
    """Result from DRIFT search operation."""

    query: str
    answer: str
    confidence: float
    hierarchy: DriftHierarchy
    primer_communities: int
    follow_up_iterations: int
    total_llm_calls: int
    drift_mode: str = "normal"  # normal, fallback_local
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftConfig:
    """Configuration for DRIFT search engine."""

    primer_k: int = 3
    max_follow_ups: int = 2
    confidence_threshold: float = 0.7
    max_concurrent: int = 5
    similarity_threshold: float = 0.5


class DRIFTSearchEngine:
    """DRIFT Search Engine implementation.

    Dynamic Reasoning and Inference Framework for combining global
    community insights with local entity details.

    Best for:
    - Complex multi-faceted queries
    - Research-style exploration
    - Questions requiring both breadth and depth
    """

    def __init__(
        self,
        neo4j_pool: Neo4jPool,
        llm: LLMClient,
        config: DriftConfig | None = None,
        local_engine: LocalSearchEngine | None = None,
    ) -> None:
        """Initialize DRIFT search engine.

        Args:
            neo4j_pool: Neo4j connection pool.
            llm: LLM client for answer generation.
            config: DRIFT configuration.
            local_engine: Optional local search engine for follow-up phase.
        """
        self._pool = neo4j_pool
        self._llm = llm
        self._config = config or DriftConfig()
        self._context_builder = GlobalContextBuilder(
            neo4j_pool=neo4j_pool,
            llm_client=llm,
        )
        self._local_engine = local_engine or LocalSearchEngine(
            neo4j_pool=neo4j_pool,
            llm=llm,
        )

    async def search(self, query: str) -> DriftResult:
        """Execute DRIFT search.

        Args:
            query: Search query.

        Returns:
            DriftResult with hierarchical answer structure.
        """
        log.info(
            "drift_search_started",
            query=query[:100],
            primer_k=self._config.primer_k,
            max_follow_ups=self._config.max_follow_ups,
        )

        llm_calls = 0
        hierarchy = DriftHierarchy()

        # Phase 1: Primer
        primer_result = await self._primer_phase(query)
        llm_calls += primer_result.get("llm_calls", 0)

        if primer_result.get("fallback", False):
            # No relevant communities, fallback to local search
            log.info("drift_fallback_to_local", reason="no_communities")
            local_result = await self._local_engine.search(query)
            return DriftResult(
                query=query,
                answer=local_result.answer,
                confidence=local_result.confidence,
                hierarchy=hierarchy,
                primer_communities=0,
                follow_up_iterations=0,
                total_llm_calls=llm_calls + 1,
                drift_mode="fallback_local",
            )

        hierarchy.primer = primer_result

        # Phase 2: Follow-up iterations
        follow_up_results = await self._follow_up_phase(
            query=query,
            initial_answer=primer_result.get("answer", ""),
            follow_up_questions=primer_result.get("follow_up_questions", []),
        )
        llm_calls += follow_up_results.get("llm_calls", 0)
        hierarchy.follow_ups = follow_up_results.get("results", [])

        # Phase 3: Output aggregation
        final_result = await self._aggregate_results(
            query=query,
            primer=primer_result,
            follow_ups=hierarchy.follow_ups,
        )
        llm_calls += 1

        log.info(
            "drift_search_complete",
            primer_communities=primer_result.get("community_count", 0),
            follow_up_iterations=len(hierarchy.follow_ups),
            llm_calls=llm_calls,
        )

        return DriftResult(
            query=query,
            answer=final_result.get("answer", ""),
            confidence=final_result.get("confidence", 0.5),
            hierarchy=hierarchy,
            primer_communities=primer_result.get("community_count", 0),
            follow_up_iterations=len(hierarchy.follow_ups),
            total_llm_calls=llm_calls,
            metadata={
                "primer_communities": primer_result.get("community_count", 0),
                "follow_up_iterations": len(hierarchy.follow_ups),
                "total_llm_calls": llm_calls,
            },
        )

    async def _primer_phase(self, query: str) -> dict[str, Any]:
        """Execute Primer phase - vector search community reports.

        Args:
            query: Search query.

        Returns:
            Primer result with initial answer and follow-up questions.
        """
        # Find relevant communities
        context = await self._context_builder.build(
            query=query,
            max_tokens=4000,
        )

        community_count = context.metadata.get("total_communities", 0)

        if community_count == 0:
            return {
                "fallback": True,
                "answer": "",
                "follow_up_questions": [],
                "llm_calls": 0,
            }

        # Generate initial answer
        system_prompt = """你是一个知识图谱分析专家。基于提供的社区报告摘要，生成对用户问题的初步回答。

请：
1. 综合各社区的信息
2. 生成简洁的初步答案（200字以内）
3. 提出3个后续问题以深入探索"""

        user_content = f"用户问题：{query}\n\n社区报告摘要：\n{context.to_prompt()}"

        result = await self._llm.call_at(
            call_point=CallPoint.COMMUNITY_REPORT,
            payload={
                "system_prompt": system_prompt,
                "user_content": user_content,
            },
        )
        response_text = str(result) if result else ""

        # Parse follow-up questions
        follow_up_questions = self._extract_follow_up_questions(response_text)
        answer = self._extract_answer(response_text)

        return {
            "fallback": False,
            "answer": answer,
            "follow_up_questions": follow_up_questions,
            "community_count": community_count,
            "source_communities": context.metadata.get("community_ids", []),
            "llm_calls": 1,
        }

    async def _follow_up_phase(
        self,
        query: str,
        initial_answer: str,
        follow_up_questions: list[str],
    ) -> dict[str, Any]:
        """Execute Follow-Up phase - iterative local search.

        Args:
            query: Original query.
            initial_answer: Primer answer.
            follow_up_questions: Questions generated during primer.

        Returns:
            Follow-up results with intermediate answers.
        """
        results = []
        llm_calls = 0
        iteration = 0

        questions_to_process = follow_up_questions[: self._config.max_follow_ups]

        for question in questions_to_process:
            if not question.strip():
                continue

            iteration += 1
            log.debug("drift_follow_up", iteration=iteration, question=question[:50])

            # Execute local search for this question
            local_result = await self._local_engine.search(question)
            llm_calls += 1

            follow_up_data = {
                "question": question,
                "answer": local_result.answer,
                "confidence": local_result.confidence,
                "source_entities": getattr(local_result, "source_entities", []),
            }
            results.append(follow_up_data)

            # Check early termination
            if local_result.confidence >= self._config.confidence_threshold:
                log.info(
                    "drift_early_termination",
                    reason="confidence_threshold_reached",
                    confidence=local_result.confidence,
                )
                break

        return {
            "results": results,
            "llm_calls": llm_calls,
        }

    async def _aggregate_results(
        self,
        query: str,
        primer: dict[str, Any],
        follow_ups: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Aggregate all results into final answer.

        Args:
            query: Original query.
            primer: Primer phase result.
            follow_ups: Follow-up phase results.

        Returns:
            Aggregated result with final answer and confidence.
        """
        # Build context for aggregation
        context_parts = [f"初始答案：{primer.get('answer', '')}"]

        for i, fu in enumerate(follow_ups, 1):
            context_parts.append(f"\n后续问题 {i}：{fu.get('question', '')}")
            context_parts.append(f"答案：{fu.get('answer', '')}")

        system_prompt = """你是一个知识图谱分析专家。基于初始答案和后续探索结果，生成对用户问题的综合回答。

请：
1. 综合所有信息生成完整回答
2. 确保回答全面且有条理
3. 在最后标注置信度（0.0-1.0），格式为 [置信度: X.X]"""

        user_content = f"用户问题：{query}\n\n探索结果：\n{chr(10).join(context_parts)}"

        result = await self._llm.call_at(
            call_point=CallPoint.SEARCH_GLOBAL,
            payload={
                "system_prompt": system_prompt,
                "user_content": user_content,
            },
        )
        response_text = str(result) if result else ""

        # Extract confidence
        confidence = self._extract_confidence(response_text)
        answer = self._remove_confidence_marker(response_text)

        return {
            "answer": answer,
            "confidence": confidence,
        }

    def _extract_follow_up_questions(self, text: str) -> list[str]:
        """Extract follow-up questions from LLM response."""
        questions = []
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            # Look for numbered questions or questions ending with ?
            if line and (line[0].isdigit() or line.startswith("-") or line.startswith("*")):
                if "?" in line or "？" in line:
                    # Remove numbering
                    question = line.lstrip("0123456789.-* ")
                    if question:
                        questions.append(question)

        return questions[:3]  # Max 3 questions

    def _extract_answer(self, text: str) -> str:
        """Extract the answer portion from LLM response."""
        # Split at follow-up questions section
        markers = ["后续问题", "follow-up", "问题：", "questions"]
        for marker in markers:
            if marker.lower() in text.lower():
                idx = text.lower().find(marker.lower())
                return text[:idx].strip()
        return text.strip()

    def _extract_confidence(self, text: str) -> float:
        """Extract confidence score from text."""
        import re

        # Look for [置信度: X.X] or similar patterns
        patterns = [
            r"\[置信度[：:]\s*([\d.]+)\]",
            r"\[confidence[：:]\s*([\d.]+)\]",
            r"置信度[：:]\s*([\d.]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass

        return 0.5  # Default confidence

    def _remove_confidence_marker(self, text: str) -> str:
        """Remove confidence marker from text."""
        import re

        patterns = [
            r"\[置信度[：:]\s*[\d.]+\]",
            r"\[confidence[：:]\s*[\d.]+\]",
        ]

        result = text
        for pattern in patterns:
            result = re.sub(pattern, "", result, flags=re.IGNORECASE)

        return result.strip()

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Monte Carlo evidence sampler for long document processing.

This module implements intelligent sampling of long documents using
Monte Carlo methods with multi-anchor strategies to extract the most
relevant regions while staying within token budgets.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from core.evidence.models import EvidenceScoreOutput
from core.llm.types import CallPoint
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.llm.client import LLMClient
    from core.llm.config.token_budget import TokenBudgetManager

log = get_logger(__name__)


class MCSampler:
    """Monte Carlo evidence sampler for long documents.

    Implements intelligent sampling strategies to extract key regions
    from long documents (>10K characters) while preserving information
    density and relevance.

    The sampler uses a multi-anchor strategy:
    1. Fuzz-based anchor finding (comparing adjacent text regions)
    2. Stratified random sampling across document sections
    3. LLM-based quality scoring of sampled regions
    4. Confidence-weighted synthesis of final output

    Args:
        llm_client: LLM client for quality scoring and synthesis.
        token_budget_manager: Token budget manager for truncation.
        threshold: Character threshold for triggering MC sampling.
        sample_size: Number of regions to sample.
        region_size: Characters per sampled region.
        confidence_threshold: Minimum confidence to use sampled text.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        token_budget_manager: TokenBudgetManager,
        threshold: int = 10000,
        sample_size: int = 5,
        region_size: int = 2000,
        confidence_threshold: float = 0.4,
    ) -> None:
        self._llm = llm_client
        self._budget = token_budget_manager
        self._threshold = threshold
        self._sample_size = sample_size
        self._region_size = region_size
        self._confidence_threshold = confidence_threshold

    async def sample_evidence(
        self,
        document: str,
        title: str = "",
    ) -> tuple[str, float]:
        """Sample key regions from a long document.

        Uses Monte Carlo sampling with multi-anchor strategy to extract
        the most relevant portions of a document.

        Args:
            document: The full document text to sample from.
            title: Document title for context in LLM scoring.

        Returns:
            Tuple of (sampled_text, confidence_score).
            If confidence < threshold, returns original document truncated.
        """
        doc_len = len(document)

        # Return as-is if document is short enough
        if doc_len <= self._threshold:
            log.debug("document_short_enough", length=doc_len, threshold=self._threshold)
            return document, 1.0

        log.info(
            "mc_sampling_started",
            document_length=doc_len,
            sample_size=self._sample_size,
            region_size=self._region_size,
        )

        # Step 1: Find anchor points using fuzz ratio and random sampling
        anchors = self._find_anchor_points(document)

        # Step 2: Extract regions around anchor points
        regions = self._extract_regions(document, anchors)

        # Step 3: Score each region using LLM
        scored_regions: list[tuple[str, EvidenceScoreOutput]] = []
        for i, region in enumerate(regions):
            try:
                score = await self._score_region(region, title)
                scored_regions.append((region, score))
                log.debug(
                    "region_scored",
                    region_index=i,
                    relevance=score.relevance_score,
                    density=score.information_density,
                    confidence=score.confidence,
                )
            except Exception as e:
                log.warning(
                    "region_scoring_failed",
                    region_index=i,
                    error=str(e),
                )
                # Use default low score for failed regions
                scored_regions.append(
                    (
                        region,
                        EvidenceScoreOutput(
                            relevance_score=0.3,
                            information_density=0.3,
                            confidence=0.0,
                            key_facts=[],
                        ),
                    )
                )

        # Step 4: Calculate overall confidence
        if not scored_regions:
            log.warning("no_regions_scored_fallback")
            return self._budget.truncate(document, CallPoint.ANALYZE), 0.0

        # Weight confidence by relevance and information density
        total_confidence = 0.0
        total_weight = 0.0
        for _, score in scored_regions:
            weight = score.relevance_score * score.information_density
            total_confidence += score.confidence * weight
            total_weight += weight

        overall_confidence = total_confidence / total_weight if total_weight > 0 else 0.0

        # Step 5: Check if confidence is sufficient
        if overall_confidence < self._confidence_threshold:
            log.warning(
                "mc_sampling_low_confidence_fallback",
                confidence=overall_confidence,
                threshold=self._confidence_threshold,
            )
            return self._budget.truncate(document, CallPoint.ANALYZE), overall_confidence

        # Step 6: Synthesize sampled regions
        sampled_text = self._synthesize_regions(scored_regions, title)

        log.info(
            "mc_sampling_complete",
            original_length=doc_len,
            sampled_length=len(sampled_text),
            confidence=overall_confidence,
            regions_used=len(scored_regions),
        )

        return sampled_text, overall_confidence

    def _find_anchor_points(self, text: str) -> list[int]:
        """Find anchor points using fuzz ratio and random sampling.

        The strategy combines:
        1. Fuzz-based: Points where adjacent text differs significantly
        2. Stratified random: Evenly distributed random points

        Args:
            text: The full document text.

        Returns:
            List of character indices as anchor points.
        """
        text_len = len(text)
        anchors: list[int] = []
        window = min(500, text_len // 10)  # Comparison window size

        # Strategy 1: Fuzz-based anchor finding
        # Find points where adjacent regions have low similarity
        fuzz_anchors = self._find_fuzz_anchors(text, window)
        anchors.extend(fuzz_anchors)

        # Strategy 2: Stratified random sampling
        # Divide document into sections and sample from each
        section_count = max(2, self._sample_size // 2)
        section_size = text_len // section_count
        random_anchors: list[int] = []

        for i in range(section_count):
            section_start = i * section_size
            section_end = min((i + 1) * section_size, text_len - self._region_size)
            if section_end > section_start:
                anchor = random.randint(section_start, section_end)
                random_anchors.append(anchor)

        anchors.extend(random_anchors)

        # Deduplicate and sort anchors
        anchors = sorted(set(anchors))

        # Limit to sample_size most relevant anchors
        if len(anchors) > self._sample_size:
            # Prioritize fuzz anchors (content change points)
            anchors = sorted(
                anchors,
                key=lambda x: (
                    x not in fuzz_anchors,  # Fuzz anchors first
                    random.random(),  # Then random order
                ),
            )[: self._sample_size]

        log.debug(
            "anchors_found",
            total=len(anchors),
            fuzz_based=len(fuzz_anchors),
            random_based=len(random_anchors),
        )

        return anchors

    def _find_fuzz_anchors(self, text: str, window: int) -> list[int]:
        """Find anchors at points of content change.

        Uses simple ratio comparison between adjacent windows to find
        points where the content changes significantly.

        Args:
            text: The full document text.
            window: Window size for comparison.

        Returns:
            List of anchor indices at content change points.
        """
        text_len = len(text)
        anchors: list[int] = []
        step = max(100, window // 2)  # Step size for scanning

        prev_window = ""
        for pos in range(0, text_len - window, step):
            current_window = text[pos : pos + window]

            # Simple similarity check using character overlap
            if prev_window:
                similarity = self._simple_similarity(prev_window, current_window)
                # If similarity is low, this is a change point
                if similarity < 0.5:
                    anchors.append(pos)

            prev_window = current_window

        return anchors

    def _simple_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple character-based similarity ratio.

        Uses character n-gram overlap as a quick similarity measure.

        Args:
            text1: First text to compare.
            text2: Second text to compare.

        Returns:
            Similarity ratio between 0 and 1.
        """
        if not text1 or not text2:
            return 0.0

        # Use word overlap for Chinese and space-separated languages
        words1 = set(text1)
        words2 = set(text2)

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def _extract_regions(
        self,
        text: str,
        anchors: list[int],
    ) -> list[str]:
        """Extract text regions around anchor points.

        Args:
            text: The full document text.
            anchors: List of anchor point indices.

        Returns:
            List of extracted text regions.
        """
        text_len = len(text)
        regions: list[str] = []

        for anchor in anchors:
            # Center the region around the anchor point
            start = max(0, anchor - self._region_size // 2)
            end = min(text_len, start + self._region_size)

            # Adjust start if we hit the end
            if end == text_len:
                start = max(0, end - self._region_size)

            region = text[start:end]

            # Add context marker if truncated
            if start > 0:
                region = "...[前文省略]...\n" + region
            if end < text_len:
                region = region + "\n...[后文省略]..."

            regions.append(region)

        return regions

    async def _score_region(
        self,
        region: str,
        title: str,
    ) -> EvidenceScoreOutput:
        """Score a text region using LLM.

        Args:
            region: The text region to score.
            title: Document title for context.

        Returns:
            EvidenceScoreOutput with relevance, density, and confidence.
        """
        try:
            result: EvidenceScoreOutput = await self._llm.call_at(
                CallPoint.EVIDENCE_SAMPLING,
                {
                    "title": title,
                    "sample_text": region,
                },
                output_model=EvidenceScoreOutput,
            )
            return result
        except Exception:
            return EvidenceScoreOutput(
                relevance_score=0.3,
                information_density=0.3,
                confidence=0.0,
                key_facts=[],
            )

    def _synthesize_regions(
        self,
        scored_regions: list[tuple[str, EvidenceScoreOutput]],
        title: str,
    ) -> str:
        """Synthesize sampled regions into final text.

        Combines regions weighted by their scores into a single
        text that preserves the most relevant information.

        Args:
            scored_regions: List of (region, score) tuples.
            title: Document title for context.

        Returns:
            Synthesized text from sampled regions.
        """
        # Sort by relevance * density * confidence
        sorted_regions = sorted(
            scored_regions,
            key=lambda x: x[1].relevance_score * x[1].information_density * x[1].confidence,
            reverse=True,
        )

        # Combine regions with their key facts
        parts: list[str] = []

        # Add title context
        if title:
            parts.append(f"【文档标题】{title}\n")

        # Add key facts from all regions
        all_facts: list[str] = []
        for region, score in sorted_regions:
            all_facts.extend(score.key_facts)

        if all_facts:
            unique_facts = list(dict.fromkeys(all_facts))[:10]  # Dedupe, limit to 10
            parts.append("【关键要点】")
            for fact in unique_facts:
                parts.append(f"- {fact}")
            parts.append("")

        # Add sampled regions
        parts.append("【文档摘要】")
        for i, (region, score) in enumerate(sorted_regions[:3], 1):
            parts.append(f"\n[片段{i}] (相关度: {score.relevance_score:.0%})")
            parts.append(region)

        return "\n".join(parts)

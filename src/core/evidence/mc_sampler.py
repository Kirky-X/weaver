# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Monte Carlo evidence sampler for long document processing.

This module implements intelligent sampling of long documents using
Monte Carlo methods with multi-anchor strategies to extract the most
relevant regions while staying within token budgets.
"""

from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING

from core.evidence.models import EvidenceBatchScoreOutput, EvidenceScoreOutput
from core.llm.types import CallPoint
from core.observability import get_logger

if TYPE_CHECKING:
    from core.llm.client import LLMClient
    from core.llm.config.token_budget import TokenBudgetManager

log = get_logger(__name__)

# Pre-compiled tokenizer patterns: ``_tokenize`` is invoked on
# every fuzz-anchor step, so keep the patterns out of the per-call path.
_WORD_RE = re.compile(r"[a-zA-Z]+")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


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

        # Step 3: Score all regions in a single batched LLM call.
        # Previously N parallel calls (asyncio.gather, one per region) — each
        # carried full prompt overhead and multiplied rate-limit pressure on
        # the free tier (rpm=5). One batched call amortizes the fixed cost.
        scored_regions = await self._score_regions_batch(regions, title)

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
                # 非密码学采样用途
                anchor = random.randint(section_start, section_end)  # nosec B311
                random_anchors.append(anchor)

        anchors.extend(random_anchors)

        # Deduplicate and sort anchors
        anchors = sorted(set(anchors))

        # Limit to sample_size most relevant anchors
        if len(anchors) > self._sample_size:
            # Prioritize fuzz anchors (content change points); ties broken by
            # position so the selection is deterministic for a given anchor
            # set (the set itself is already randomly sampled above).
            # frozenset for O(1) membership instead of O(n) list scan.
            fuzz_anchors_set = frozenset(fuzz_anchors)
            anchors = sorted(
                anchors,
                key=lambda x: (
                    x not in fuzz_anchors_set,  # Fuzz anchors first
                    x,
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
        # Short documents (text_len < 10) yield window == 0; slicing then
        # produces empty strings and every step is flagged as a change point.
        if window <= 0:
            return []
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
        """Calculate word-level similarity ratio (fix).

        Uses word-level tokenization instead of character-level:
        - English: ``[a-zA-Z]+`` word tokens
        - Chinese: 2-gram sliding window over CJK runs

        Character-level ``set(text)`` gave false-high similarity for
        disjoint English words sharing common letters (e.g. ``alpha``
        vs ``gamma`` shared ``a/m/l``). Word-level fixes this.

        Args:
            text1: First text to compare.
            text2: Second text to compare.

        Returns:
            Similarity ratio between 0 and 1.
        """
        if not text1 or not text2:
            return 0.0

        words1 = set(self._tokenize(text1))
        words2 = set(self._tokenize(text2))

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text into word-level tokens (fix).

        - English / Latin: ``re.findall(r'[a-zA-Z]+', text)``
        - Chinese (CJK): 2-gram sliding window over each CJK run
          (e.g. ``技术发展`` → ``[技术, 术发, 发展]``)

        Non-CJK / non-Latin characters are ignored (punctuation,
        digits, whitespace) — they don't carry semantic similarity
        signal at this granularity.

        Args:
            text: Input text.

        Returns:
            List of tokens.
        """
        tokens: list[str] = []

        # English / Latin words
        tokens.extend(_WORD_RE.findall(text))

        # Chinese 2-grams: for each CJK run, slide a 2-char window
        for cjk_run in _CJK_RUN_RE.findall(text):
            if len(cjk_run) < 2:
                # Single CJK char — treat as a token
                tokens.append(cjk_run)
                continue
            for i in range(len(cjk_run) - 1):
                tokens.append(cjk_run[i : i + 2])

        return tokens

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

    async def _score_regions_batch(
        self,
        regions: list[str],
        title: str,
    ) -> list[tuple[str, EvidenceScoreOutput]]:
        """Score all sampled regions in a single LLM call.

        Payload carries numbered regions (R1..Rn); the LLM returns one JSON
        object whose ``scores`` elements echo ``region_id``. Alignment uses
        region_id when the model echoes them all, else falls back to array
        order. Length mismatch retries once; any failure degrades ALL
        regions to default low scores — the caller's low-confidence
        fallback (truncate original) then applies.

        Args:
            regions: Sampled text regions.
            title: Document title for context.

        Returns:
            List of (region, EvidenceScoreOutput) tuples, index-aligned.
        """
        regions_payload = {
            f"R{i}": self._budget.truncate(region, CallPoint.EVIDENCE_SAMPLING)
            for i, region in enumerate(regions, start=1)
        }

        scores: list[EvidenceScoreOutput] | None = None
        for attempt in (1, 2):
            try:
                result: EvidenceBatchScoreOutput = await self._llm.call_at(
                    CallPoint.EVIDENCE_SAMPLING,
                    {
                        "title": title,
                        "regions": regions_payload,
                    },
                    output_model=EvidenceBatchScoreOutput,
                )
                scores = list(result.scores)
            except Exception:
                log.warning(
                    "batch_region_scoring_failed",
                    attempt=attempt,
                    exc_info=True,
                )
                scores = None
            if scores is not None and len(scores) == len(regions):
                break
            log.warning(
                "region_scores_length_mismatch",
                attempt=attempt,
                expected=len(regions),
                got=len(scores) if scores is not None else -1,
            )
            scores = None

        if scores is None:
            return [(region, self._default_score()) for region in regions]
        return self._align_scores(regions, scores)

    @staticmethod
    def _align_scores(
        regions: list[str],
        scores: list[EvidenceScoreOutput],
    ) -> list[tuple[str, EvidenceScoreOutput]]:
        """Align batch scores to regions: by echoed region_id when complete.

        LLM batch outputs can arrive out of order — array order is only a
        fallback for models that skip the region_id echo. If region_ids are
        present but don't cover exactly R1..Rn, degrade to defaults rather
        than risk attributing a score to the wrong region.
        """
        expected_ids = [f"R{i}" for i in range(1, len(regions) + 1)]
        echoed = [s.region_id for s in scores]
        if all(echoed) and sorted(echoed) == sorted(expected_ids):
            by_id = {s.region_id: s for s in scores}
            return [(region, by_id[rid]) for region, rid in zip(regions, expected_ids, strict=True)]
        if any(echoed):
            log.warning("region_id_echo_incomplete", echoed=sum(1 for e in echoed if e))
        return list(zip(regions, scores, strict=True))

    @staticmethod
    def _default_score() -> EvidenceScoreOutput:
        """Default low-confidence score for degraded regions."""
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

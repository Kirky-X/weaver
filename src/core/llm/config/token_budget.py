# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Token budget management with tiktoken truncation."""

from __future__ import annotations

import tiktoken

from core.llm.types import CallPoint
from core.observability import get_logger

log = get_logger(__name__)

# Per-call-point token limits
LIMITS: dict[CallPoint, int] = {
    # Article processing pipeline
    CallPoint.CLASSIFIER: 1000,
    CallPoint.CLEANER: 6000,
    CallPoint.CATEGORIZER: 1000,
    CallPoint.MERGER: 8000,
    CallPoint.ANALYZE: 4000,
    # 合并调用点取 narrative 侧 8000（保守不折中：narrative 的 event_type/
    # pattern 依赖更长上下文，且 RPM 是硬约束、token 不是）
    CallPoint.ANALYZE_NARRATIVE: 8000,
    CallPoint.CREDIBILITY_CHECKER: 3000,
    CallPoint.QUALITY_SCORER: 3000,
    # Entity extraction & resolution
    CallPoint.ENTITY_EXTRACTOR: 4000,
    # entity-resolver-batch-select: 文档性额度（该 call_point 无 truncate 消费点）。
    # 批量 payload 体量由 MAX_BATCH_LLM_ENTITIES(20) x 候选数(<=5) 约束。
    CallPoint.ENTITY_RESOLVER: 3000,
    # GLiNER refine：单实体小 payload，对齐 COMMUNITY_TITLE 量级。
    CallPoint.ENTITY_REFINE: 1000,
    # Embedding & reranking
    CallPoint.EMBEDDING: 500,
    CallPoint.RERANK: 500,
    # Search operations
    CallPoint.SEARCH_LOCAL: 1000,
    CallPoint.SEARCH_GLOBAL: 1000,
    # Community & graph operations
    CallPoint.COMMUNITY_REPORT: 6000,
    CallPoint.COMMUNITY_TITLE: 1000,
    CallPoint.ENTITY_FACTS: 3000,
    # Advanced analysis
    CallPoint.CAUSAL_INFERENCE: 4000,
    CallPoint.NARRATIVE_SYNTHESIS: 8000,
    CallPoint.NARRATIVE_SCHEMA: 8000,
    # 批量评分 per-region 防御网上限。整批体量由构造参数约束
    # （sample_size × region_size = 5×2000 字符；中文最坏 ~1.5 token/字符
    # 即整批可达 ~15k tokens），不依赖此限额做总量守门。
    CallPoint.EVIDENCE_SAMPLING: 4000,
    CallPoint.SENTIMENT: 1000,
    CallPoint.CLAIM_EXTRACTION: 3000,
    # Briefing: multi-article per-category summary (same scale as
    # COMMUNITY_REPORT).
    CallPoint.BRIEFING: 6000,
    # Query expander: input is a short search query — tight budget.
    CallPoint.QUERY_EXPANDER: 500,
}

DEFAULT_LIMIT = 4000


class TokenBudgetManager:
    """Manages token budgets by truncating text to fit model context limits.

    Uses a 70/30 head/tail split to preserve both the introduction
    (head) and conclusion (tail) of news articles.

    Args:
        model: The model name for tiktoken encoding lookup.
    """

    def __init__(self, model: str | None = None) -> None:
        """Initialize token budget manager.

        Args:
            model: Model name for tiktoken encoding. When None, attempts to read
                from settings.llm.tokenizer_model first. Falls back to "gpt-4o"
                which uses cl100k_base encoding (standard for modern OpenAI models).
                Unknown models gracefully fall back to cl100k_base encoding.
        """
        resolved = model or self._resolve_from_settings() or "gpt-4o"
        try:
            self._enc = tiktoken.encoding_for_model(resolved)
        except KeyError:
            # Fallback to cl100k_base for unknown models
            self._enc = tiktoken.get_encoding("cl100k_base")

    @staticmethod
    def _resolve_from_settings() -> str | None:
        """Try to read tokenizer_model from settings.

        Returns:
            Configured tokenizer model name, or None if not configured.
        """
        try:
            from config.settings import get_settings

            settings = get_settings()
            return settings.llm.tokenizer_model
        except Exception as exc:
            # 记录具体异常类型：仅 "falling back to default" 无法区分
            # ImportError（无 config 包）与配置项错误（llm 属性缺失等）。
            log.warning(
                "tokenizer_model_unresolved",
                error_type=type(exc).__name__,
                error=str(exc),
                exc_info=True,
            )
            return None

    def truncate(self, text: str, call_point: CallPoint) -> str:
        """Truncate text to fit the token budget for the given call point.

        Preserves the first 70% and last 30% of tokens to retain
        article lead and conclusion.

        Args:
            text: Input text to truncate.
            call_point: The pipeline call point determining the budget.

        Returns:
            Original text if within budget, or truncated text.
        """
        limit = LIMITS.get(call_point, DEFAULT_LIMIT)
        tokens = self._enc.encode(text)

        if len(tokens) <= limit:
            return text

        # 70% head + 30% tail
        head_n = int(limit * 0.7)
        tail_n = limit - head_n
        head = self._enc.decode(tokens[:head_n])
        tail = self._enc.decode(tokens[-tail_n:])
        return head + "\n...[内容截断]...\n" + tail

    def count_tokens(self, text: str) -> int:
        """Count the number of tokens in the given text.

        Args:
            text: Input text.

        Returns:
            Token count.
        """
        return len(self._enc.encode(text))

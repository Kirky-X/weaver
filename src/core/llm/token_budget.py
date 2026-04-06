# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Token budget management with tiktoken truncation."""

from __future__ import annotations

import tiktoken

from core.llm.types import CallPoint

# Per-call-point token limits
LIMITS: dict[CallPoint, int] = {
    CallPoint.CLEANER: 6000,
    CallPoint.ANALYZE: 4000,
    CallPoint.ENTITY_EXTRACTOR: 4000,
    CallPoint.CREDIBILITY_CHECKER: 3000,
    CallPoint.QUALITY_SCORER: 3000,
    CallPoint.CLASSIFIER: 1000,
    CallPoint.MERGER: 8000,
}

DEFAULT_LIMIT = 4000


class TokenBudgetManager:
    """Manages token budgets by truncating text to fit model context limits.

    Uses a 70/30 head/tail split to preserve both the introduction
    (head) and conclusion (tail) of news articles.

    Args:
        model: The model name for tiktoken encoding lookup.
    """

    def __init__(self, model: str = "gpt-4o") -> None:
        """Initialize token budget manager.

        Args:
            model: Model name for tiktoken encoding. Defaults to "gpt-4o" because
                it uses the cl100k_base encoding which is the standard for modern
                OpenAI models (GPT-4, GPT-4o, GPT-3.5-turbo). This encoding provides
                accurate token counting for Chinese text and is widely supported.
                Unknown models gracefully fall back to cl100k_base encoding.
        """
        try:
            self._enc = tiktoken.encoding_for_model(model)
        except KeyError:
            # Fallback to cl100k_base for unknown models
            self._enc = tiktoken.get_encoding("cl100k_base")

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

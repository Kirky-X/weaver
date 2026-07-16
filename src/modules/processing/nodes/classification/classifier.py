# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Cascade classifier — rule-first, ML cascade, LLM fallback."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.llm.client import LLMClient
    from core.llm.config.token_budget import TokenBudgetManager
    from core.prompt.loader import PromptLoader
    from modules.processing.nodes.classification.cascade_classifier import CascadeClassifier

log = get_logger(__name__)

NEWS_KEYWORDS = [
    "报道",
    "发布",
    "宣布",
    "声明",
    "公告",
    "据悉",
    "消息",
    "据报道",
    "记者",
    "快讯",
    "预警",
    "通报",
    "通知",
    "我国",
    "国家",
    "政府",
    "部门",
    "机构",
]

NON_NEWS_KEYWORDS = [
    "登录",
    "注册",
    "密码",
    "账号",
    "产品介绍",
    "使用教程",
    "下载",
    "安装",
    "配置",
    "常见问题",
    "帮助中心",
]

NEWS_URL_PATTERNS = [
    r"/news/",
    r"/article/",
    r"/story/",
    r"/p/\d+",
    r"news\.",
    r"\.news",
]


class CascadeClassifierNode:
    """Pipeline node: cascade classifier with rule-first, LLM-fallback."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        budget: TokenBudgetManager | None = None,
        prompt_loader: PromptLoader | None = None,
        cascade: CascadeClassifier | None = None,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._cascade = cascade

    async def execute(self, state: PipelineState) -> PipelineState:
        raw = state["raw"]
        title = raw.title
        url = raw.url

        is_news_rule = self._rule_classify(title, url)

        if is_news_rule is not None:
            state["is_news"] = is_news_rule
            state["terminal"] = not is_news_rule
            log.info("cascade_rule_match", title=title, is_news=is_news_rule)
            return state

        # Layer 1-3: ML cascade (fastText → SetFit → fusion)
        if self._cascade:
            result = self._cascade.classify(title)
            if result is not None:
                label, confidence = result
                state["is_news"] = label in ("news", "1", "true")
                state["terminal"] = not state["is_news"]
                log.info("cascade_ml_match", title=title, label=label, confidence=confidence)
                return state

        if self._llm and self._budget and self._prompt_loader:
            from core.llm.types import CallPoint
            from core.llm.validation.output_validator import ClassifierOutput

            payload = {
                "title": title,
                "body_snippet": self._budget.truncate(raw.body, CallPoint.CLASSIFIER),
                "article_id": state.get("article_id"),
                "task_id": state.get("task_id"),
            }
            result: ClassifierOutput = await self._llm.call_at(
                CallPoint.CLASSIFIER,
                payload,
                output_model=ClassifierOutput,
                article_id=state.get("article_id"),
                task_id=state.get("task_id"),
            )
            state["is_news"] = result.is_news if result.is_news is not None else False
            state["terminal"] = not state["is_news"]

            state.setdefault("prompt_versions", {})["classifier"] = (
                self._prompt_loader.get_version("classifier")
                if hasattr(self._prompt_loader, "get_version")
                else "unknown"
            )
        else:
            state["is_news"] = True
            state["terminal"] = False

        log.info("classified", url=url, is_news=state["is_news"])
        return state

    @staticmethod
    def _rule_classify(title: str, url: str) -> bool | None:
        title_lower = title.lower()

        news_count = sum(1 for kw in NEWS_KEYWORDS if kw in title)
        non_news_count = sum(1 for kw in NON_NEWS_KEYWORDS if kw in title_lower)

        if news_count >= 2:
            return True
        if non_news_count >= 2:
            return False
        if news_count == 1 and non_news_count == 0:
            return True

        for pattern in NEWS_URL_PATTERNS:
            if re.search(pattern, url):
                return True

        if len(title) < 5:
            return False

        return None

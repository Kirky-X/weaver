# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Cascade categorizer — rule-first, LLM fallback."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.llm.client import LLMClient
    from core.prompt.loader import PromptLoader

log = get_logger(__name__)

CATEGORY_MAP = {
    "technology": "科技",
    "tech": "科技",
    "politics": "政治",
    "political": "政治",
    "military": "军事",
    "army": "军事",
    "economy": "经济",
    "economic": "经济",
    "business": "经济",
    "society": "社会",
    "social": "社会",
    "culture": "文化",
    "cultural": "文化",
    "sports": "体育",
    "sport": "体育",
    "international": "国际",
    "world": "国际",
    "global": "国际",
}

EMOTION_MAP = {
    "optimistic": "乐观",
    "hope": "期待",
    "excited": "振奋",
    "calm": "平静",
    "neutral": "客观",
    "objective": "客观",
    "worried": "担忧",
    "concern": "担忧",
    "pessimistic": "悲观",
    "sad": "悲观",
    "angry": "愤怒",
    "anger": "愤怒",
    "panic": "恐慌",
    "fear": "恐慌",
}

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "经济": ["股市", "GDP", "央行", "货币", "财政", "贸易", "关税", "通胀", "通缩", "降息", "加息"],
    "军事": [
        "军事",
        "国防",
        "军队",
        "导弹",
        "战机",
        "演习",
        "航母",
        "军舰",
        "坦克",
        "武装",
        "冲突",
    ],
    "科技": [
        "科技",
        "AI",
        "人工智能",
        "芯片",
        "数据",
        "互联网",
        "算法",
        "数字化",
        "机器人",
        "大模型",
    ],
    "体育": ["体育", "比赛", "夺冠", "冠军", "奥运", "世界杯", "联赛", "运动员", "进球"],
    "政治": ["政治", "选举", "议会", "总统", "总理", "外交", "立法", "政策", "改革", "执政"],
    "社会": ["社会", "民生", "教育", "医疗", "养老", "就业", "住房", "交通", "环境", "公益"],
    "文化": ["文化", "艺术", "展览", "演出", "电影", "音乐", "文学", "非遗", "传统"],
    "国际": ["国际", "全球", "联合国", "WTO", "北约", "欧盟", "峰会", "制裁", "大使"],
}

VALID_CATEGORIES = {"政治", "军事", "经济", "科技", "社会", "文化", "体育", "国际"}


def normalize_category(cat: str) -> str:
    """Normalize category to Chinese value."""
    if not cat:
        return "社会"
    cat_lower = cat.lower().strip()
    result = CATEGORY_MAP.get(cat_lower, cat)
    log.debug("normalize_category", input=cat, output=result)
    if result not in VALID_CATEGORIES:
        return "社会"
    return result


def normalize_emotion(emo: str) -> str:
    """Normalize emotion to Chinese value."""
    if not emo:
        return "客观"
    emo_lower = emo.lower().strip()
    result = EMOTION_MAP.get(emo_lower, emo)
    log.debug("normalize_emotion", input=emo, output=result)
    return result


def _has_chinese(text: str) -> bool:
    """Check if text contains Chinese characters."""
    return bool(re.search(r"[\u4e00-\u9fff]", text))


class CascadeCategorizerNode:
    """Pipeline node: cascade categorizer with rule-first, LLM-fallback.

    Implements: CascadeCategorizerNode
    """

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt_loader: PromptLoader | None = None,
        cascade: Any | None = None,
    ) -> None:
        self._llm = llm
        self._prompt_loader = prompt_loader
        self._cascade = cascade

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.get("terminal"):
            return state

        cleaned = state["cleaned"]
        title = cleaned.get("title", "")

        rule_category = self._rule_categorize(title)

        if rule_category is not None:
            state["category"] = rule_category
            if _has_chinese(title):
                state["language"] = "zh"
                state["region"] = "中国"
            else:
                state["language"] = "en"
                state["region"] = "国际"
            log.info("cascade_rule_match", title=title, category=rule_category)
            return state

        if self._llm:
            from core.llm.types import CallPoint
            from core.llm.validation.output_validator import CategorizerOutput

            try:
                result = await self._llm.call_at(
                    CallPoint.CATEGORIZER,
                    {
                        "title": title,
                        "body": cleaned.get("body", "")[:2000],
                        "article_id": state.get("article_id"),
                        "task_id": state.get("task_id"),
                    },
                    output_model=CategorizerOutput,
                )

                state["category"] = normalize_category(result.category)
                state["language"] = result.language.strip()[:10]
                state["region"] = result.region.strip()[:50]
            except Exception as e:
                log.warning(
                    "categorizer_failed_using_defaults",
                    error=str(e),
                    url=state["raw"].url,
                )
                state["category"] = "社会"
                state["language"] = "en"
                state["region"] = "国际"
                state.setdefault("degraded_fields", []).extend(["category", "language", "region"])
                state.setdefault("degradation_reasons", {}).update(
                    {
                        "category": f"LLM categorizer failed: {e!s}",
                        "language": f"LLM categorizer failed: {e!s}",
                        "region": f"LLM categorizer failed: {e!s}",
                    }
                )

            state.setdefault("prompt_versions", {})["categorizer"] = (
                self._prompt_loader.get_version("categorizer")
                if self._prompt_loader and hasattr(self._prompt_loader, "get_version")
                else "unknown"
            )
        else:
            state["category"] = "社会"
            state["language"] = "en"
            state["region"] = "国际"

        log.info(
            "categorized",
            url=state["raw"].url,
            category=state["category"],
            language=state["language"],
        )
        return state

    @staticmethod
    def _rule_categorize(title: str) -> str | None:
        """Categorize by rules. Returns category string if certain, None if uncertain."""
        title_lower = title.lower()

        best_category: str | None = None
        best_count = 0

        for category, keywords in CATEGORY_KEYWORDS.items():
            count = 0
            for kw in keywords:
                if kw in title or kw.lower() in title_lower:
                    count += 1
            if count > best_count:
                best_count = count
                best_category = category

        if best_count >= 1:
            return best_category

        return None

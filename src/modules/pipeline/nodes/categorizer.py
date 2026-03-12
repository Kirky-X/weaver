"""Categorizer pipeline node — LLM-based category/language/region detection."""

from __future__ import annotations

from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.llm.output_validator import CategorizerOutput
from core.prompt.loader import PromptLoader
from core.observability.logging import get_logger
from modules.pipeline.state import PipelineState

log = get_logger("node.categorizer")

# Category mapping: English -> Chinese
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

# Emotion mapping: English -> Chinese
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


def normalize_category(cat: str) -> str:
    """Normalize category to Chinese value."""
    if not cat:
        return "未知"
    cat_lower = cat.lower().strip()
    result = CATEGORY_MAP.get(cat_lower, cat)
    print(f"[DEBUG] normalize_category: '{cat}' -> '{result}'")
    return result


def normalize_emotion(emo: str) -> str:
    """Normalize emotion to Chinese value."""
    if not emo:
        return "客观"
    emo_lower = emo.lower().strip()
    result = EMOTION_MAP.get(emo_lower, emo)
    print(f"[DEBUG] normalize_emotion: '{emo}' -> '{result}'")
    return result


class CategorizerNode:
    """Pipeline node: categorize articles by topic, language, and region."""

    def __init__(self, llm: LLMClient, prompt_loader: PromptLoader) -> None:
        self._llm = llm
        self._prompt_loader = prompt_loader

    async def execute(self, state: PipelineState) -> PipelineState:
        """Categorize the cleaned article."""
        if state.get("terminal"):
            return state

        cleaned = state["cleaned"]

        try:
            result: CategorizerOutput = await self._llm.call(
                CallPoint.CATEGORIZER,
                {"title": cleaned["title"], "body": cleaned["body"][:2000]},
                output_model=CategorizerOutput,
            )

            # Normalize category to Chinese
            state["category"] = normalize_category(result.category)
            state["language"] = result.language
            state["region"] = result.region
        except Exception as e:
            # Fallback: use default values if LLM fails
            log.warning("categorizer_failed_using_defaults", error=str(e), url=state["raw"].url)
            state["category"] = "未知"
            state["language"] = "en"
            state["region"] = "国际"

        state.setdefault("prompt_versions", {})["categorizer"] = (
            self._prompt_loader.get_version("categorizer")
        )

        log.info(
            "categorized",
            url=state["raw"].url,
            category=state["category"],
            language=state["language"],
        )
        return state

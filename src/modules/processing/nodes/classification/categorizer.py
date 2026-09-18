# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Cascade categorizer — rule-first, LLM fallback."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from core.constants import LanguageCode
from core.db import CategoryType, EmotionType
from core.observability import get_logger
from core.utils.paths import CONFIG_DIR
from core.utils.toml_loader import load_toml_or_warn
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.llm.client import LLMClient
    from core.prompt.loader import PromptLoader

log = get_logger(__name__)

# Category / emotion normalization vocabularies are stored as data in
# config/categorization.toml instead of being hardcoded here.
_CATEGORIZATION_FILE = CONFIG_DIR / "categorization.toml"


def _load_categorization_data() -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Load category/emotion vocabularies from config/categorization.toml.

    Targets are validated against the canonical ``CategoryType`` / ``EmotionType``
    enums (the DB column source of truth); any entry pointing at an unknown
    canonical value is dropped with a warning so a stale config file can never
    cause an invalid enum write downstream. A missing/malformed file degrades to
    empty mappings, in which case ``normalize_category``/``normalize_emotion``
    pass input through or fall back to their defaults.
    """
    data = load_toml_or_warn(_CATEGORIZATION_FILE, event="categorization_config")
    category_values = {c.value for c in CategoryType}
    emotion_values = {e.value for e in EmotionType}

    category_map: dict[str, str] = {}
    for src, target in (data.get("category_aliases") or {}).items():
        if target not in category_values:
            log.warning("category_alias_target_invalid", alias=src, target=target)
            continue
        category_map[str(src).lower()] = str(target)

    emotion_map: dict[str, str] = {}
    for src, target in (data.get("emotion_aliases") or {}).items():
        if target not in emotion_values:
            log.warning("emotion_alias_target_invalid", alias=src, target=target)
            continue
        emotion_map[str(src).lower()] = str(target)

    valid_categories: set[str] = set()
    for cat in data.get("valid_categories") or []:
        if cat not in category_values:
            log.warning("valid_category_not_in_enum", category=cat)
            continue
        valid_categories.add(str(cat))

    return category_map, emotion_map, valid_categories


CATEGORY_MAP, EMOTION_MAP, VALID_CATEGORIES = _load_categorization_data()

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

SOURCE_HOST_REGION_MAP: dict[str, str] = {
    ".cn": "中国",
    ".com.cn": "中国",
    ".jp": "日本",
    ".co.jp": "日本",
    ".kr": "韩国",
    ".co.kr": "韩国",
    ".us": "美国",
    ".uk": "英国",
    ".co.uk": "英国",
    ".de": "德国",
    ".fr": "法国",
}

# Precomputed longest-suffix-first ordering. ``infer_region_from_source_host``
# runs once per article, so the invariant sort is done once at import time
# instead of allocating and sorting a new list on every call.
_SUFFIXES_BY_LENGTH_DESC: tuple[str, ...] = tuple(
    sorted(SOURCE_HOST_REGION_MAP, key=len, reverse=True)
)

# CJK detection runs on the classification hot path — compile the pattern once.
_CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def infer_region_from_source_host(source_host: str) -> str:
    """Infer region from source_host TLD using SOURCE_HOST_REGION_MAP.

    Checks longer suffixes first (e.g., .com.cn before .cn) to avoid
    false matches.

    Args:
        source_host: The hostname to check (e.g., "news.cn", "bbc.co.uk").

    Returns:
        Region string, defaults to "国际" if no mapping found.
    """
    if not source_host:
        return "国际"
    host_lower = source_host.lower()
    # Precomputed at module level: sorted by suffix length descending so
    # .com.cn matches before .cn. Invariant, so no per-call sort/allocation.
    for suffix in _SUFFIXES_BY_LENGTH_DESC:
        if host_lower.endswith(suffix):
            return SOURCE_HOST_REGION_MAP[suffix]
    return "国际"


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
    return bool(_CHINESE_CHAR_RE.search(text))


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

    def _get_prompt_version(self) -> str:
        """Read the categorizer prompt version, degrading on lookup failure.

        ``PromptLoader.get_version`` raises ``FileNotFoundError`` when the
        prompt TOML is missing; that must not crash the pipeline node.
        """
        if not self._prompt_loader or not hasattr(self._prompt_loader, "get_version"):
            return "unknown"
        try:
            return self._prompt_loader.get_version("categorizer")
        except Exception as exc:
            log.warning(
                "categorizer_prompt_version_lookup_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            return "unknown"

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.get("terminal"):
            return state

        cleaned = state["cleaned"]
        title = cleaned.get("title", "")

        rule_category = self._rule_categorize(title)

        if rule_category is not None:
            state["category"] = rule_category
            state["language"] = (
                LanguageCode.ZH.value if _has_chinese(title) else LanguageCode.EN.value
            )
            source_host = getattr(state["raw"], "source_host", "") or ""
            state["region"] = infer_region_from_source_host(source_host)
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
                    article_id=state.get("article_id"),
                    task_id=state.get("task_id"),
                )

                state["category"] = normalize_category(result.category)
                state["language"] = result.language.strip()[:10]
                # LLM region (content-based) takes priority; fall back to
                # TLD-based rule only when LLM didn't return a region.
                if result.region and result.region.strip():
                    state["region"] = result.region.strip()[:50]
                else:
                    source_host = getattr(state["raw"], "source_host", "") or ""
                    state["region"] = infer_region_from_source_host(source_host)
            except Exception as e:
                log.warning(
                    "categorizer_failed_using_defaults",
                    error=str(e),
                    exc_type=type(e).__name__,
                    url=state["raw"].url,
                )
                state["category"] = "社会"
                # Fallback language: detect from title instead of hard-coding
                # "en". chinanews and most RSS sources are Chinese; only fall
                # back to "en" when title has no CJK characters.
                state["language"] = (
                    LanguageCode.ZH.value if _has_chinese(title) else LanguageCode.EN.value
                )
                source_host = getattr(state["raw"], "source_host", "") or ""
                state["region"] = infer_region_from_source_host(source_host)
                state.setdefault("degraded_fields", []).extend(["category", "language", "region"])
                state.setdefault("degradation_reasons", {}).update(
                    {
                        "category": f"LLM categorizer failed: {e!s}",
                        "language": f"LLM categorizer failed: {e!s}",
                        "region": f"LLM categorizer failed: {e!s}",
                    }
                )

            state.setdefault("prompt_versions", {})["categorizer"] = self._get_prompt_version()
        else:
            state["category"] = "社会"
            # No LLM available: detect language from title instead of
            # hard-coding "en" (which mislabels Chinese articles).
            state["language"] = (
                LanguageCode.ZH.value if _has_chinese(title) else LanguageCode.EN.value
            )
            source_host = getattr(state["raw"], "source_host", "") or ""
            state["region"] = infer_region_from_source_host(source_host)

        log.info(
            "categorized",
            url=state["raw"].url,
            category=state["category"],
            language=state["language"],
        )
        return state

    # Word-boundary patterns for short ASCII keywords. A bare substring
    # match turns "AI" into a hit inside "said"/"maintain"/"available",
    # producing frequent false-positive 科技 categorizations.
    _ASCII_KW_PATTERNS: dict[str, re.Pattern[str]] = {}

    @classmethod
    def _keyword_matches(cls, kw: str, title: str, title_lower: str) -> bool:
        """Match a keyword against the title.

        ASCII alnum keywords require word boundaries; CJK keywords fall
        back to plain substring matching (no word separators exist).
        """
        kw_lower = kw.lower()
        if kw_lower.isascii() and kw_lower.isalnum():
            pattern = cls._ASCII_KW_PATTERNS.get(kw_lower)
            if pattern is None:
                pattern = re.compile(rf"\b{re.escape(kw_lower)}\b")
                cls._ASCII_KW_PATTERNS[kw_lower] = pattern
            return pattern.search(title_lower) is not None
        return kw in title or kw_lower in title_lower

    @staticmethod
    def _rule_categorize(title: str) -> str | None:
        """Categorize by rules. Returns category string if certain, None if uncertain."""
        title_lower = title.lower()

        best_category: str | None = None
        best_count = 0

        for category, keywords in CATEGORY_KEYWORDS.items():
            count = 0
            for kw in keywords:
                if CascadeCategorizerNode._keyword_matches(kw, title, title_lower):
                    count += 1
            if count > best_count:
                best_count = count
                best_category = category

        if best_count >= 1:
            return best_category

        return None

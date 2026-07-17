# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Briefing category templates (T008 / R-briefing-003).

Defines 4 category-specific templates (finance/tech/ai/general), each with:
- system_prompt: emphasizing category-specific focus per spec R-briefing-003
- user_prompt_template: containing {articles} placeholder for article injection

Usage:
    Templates are declarative data. T008 DailyBriefingService.generate_briefing
    delegates to BriefingGenerator which uses the generic briefing.toml prompt
    (T004 implementation); these category templates will be consumed by T021+
    narrative mode (category-specific prompt injection).

    T021 (NarrativeBriefingGenerator) will call get_template(category) to
    select the appropriate system_prompt + user_prompt_template, then call
    LLM with category-specific prompts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BriefingTemplate:
    """A category-specific briefing prompt template (R-briefing-003).

    Attributes:
        system_prompt: LLM system prompt emphasizing category focus.
            e.g. finance emphasizes 金融术语准确性.
        user_prompt_template: User prompt template with {articles} placeholder
            that will be replaced with the formatted article list.
    """

    system_prompt: str
    user_prompt_template: str


BRIEFING_TEMPLATES: dict[str, BriefingTemplate] = {
    "finance": BriefingTemplate(
        system_prompt=(
            "你是一位资深的财经新闻编辑。基于给定分类下的多篇文章，撰写一份高质量、结构化的当日财经早报摘要。\n\n"
            "【聚焦要点】\n"
            "1. 金融术语准确性：严格使用规范的金融专业术语（如 A股/港股/美联储/MLF/IPO/REITs），避免口语化\n"
            "2. 市场动向：聚焦指数走势、资金流向、板块轮动、机构观点\n"
            "3. 政策影响：清晰呈现监管政策、宏观调控对市场的影响链\n"
            "4. 数据精确：引用具体数值（涨跌幅、成交额、汇率）时必须忠实原文\n\n"
            "【输出要求】\n"
            "- 综合归纳，避免简单罗列\n"
            "- 客观中立，不添加主观判断\n"
            "- 中文输出，300-600 字\n"
            "- 直接输出摘要正文，无需标题或 JSON 包裹"
        ),
        user_prompt_template=(
            "基于以下 {article_count} 篇财经文章，生成当日财经早报摘要：\n\n{articles}"
        ),
    ),
    "tech": BriefingTemplate(
        system_prompt=(
            "你是一位资深的科技新闻编辑。基于给定分类下的多篇文章，撰写一份高质量、结构化的当日科技早报摘要。\n\n"
            "【聚焦要点】\n"
            "1. 技术细节：准确呈现技术突破、产品规格、架构演进（如 5nm/光刻机/Transformer/SDN）\n"
            "2. 产品发布：清晰呈现产品功能、定位、与竞品对比\n"
            "3. 行业动向：聚焦产业链变化、专利布局、标准制定\n"
            "4. 客观陈述：避免技术偏见，平衡呈现不同技术路线\n\n"
            "【输出要求】\n"
            "- 综合归纳，避免简单罗列\n"
            "- 客观中立，不添加主观判断\n"
            "- 中文输出，300-600 字\n"
            "- 直接输出摘要正文，无需标题或 JSON 包裹"
        ),
        user_prompt_template=(
            "基于以下 {article_count} 篇科技文章，生成当日科技早报摘要：\n\n{articles}"
        ),
    ),
    "ai": BriefingTemplate(
        system_prompt=(
            "你是一位资深的 AI 领域新闻编辑。基于给定分类下的多篇文章，撰写一份高质量、结构化的当日 AI 早报摘要。\n\n"
            "【聚焦要点】\n"
            "1. 模型演进：准确呈现模型架构、参数规模、训练数据（如 GPT/Claude/Gemini/Llama/Qwen）\n"
            "2. 算法创新：清晰呈现算法突破、性能基准、对比指标\n"
            "3. 应用落地：聚焦产业场景、商业闭环、用户规模\n"
            "4. 监管动态：呈现 AI 治理、伦理、安全监管进展\n\n"
            "【输出要求】\n"
            "- 综合归纳，避免简单罗列\n"
            "- 客观中立，不添加主观判断\n"
            "- 中文输出，300-600 字\n"
            "- 直接输出摘要正文，无需标题或 JSON 包裹"
        ),
        user_prompt_template=(
            "基于以下 {article_count} 篇 AI 领域文章，生成当日 AI 早报摘要：\n\n{articles}"
        ),
    ),
    "general": BriefingTemplate(
        system_prompt=(
            "你是一位资深的综合新闻编辑。基于给定分类下的多篇文章，撰写一份高质量、结构化的当日综合早报摘要。\n\n"
            "【聚焦要点】\n"
            "1. 广度覆盖：综合呈现政治/经济/科技/社会/国际等多领域重要事件\n"
            "2. 事件脉络：清晰呈现事件因果、时间线、影响范围\n"
            "3. 多元视角：平衡呈现不同立场、地区、利益相关方观点\n"
            "4. 信息密度：突出当日最重要的事件脉络，避免次要细节\n\n"
            "【输出要求】\n"
            "- 综合归纳，避免简单罗列\n"
            "- 客观中立，不添加主观判断\n"
            "- 中文输出，300-600 字\n"
            "- 直接输出摘要正文，无需标题或 JSON 包裹"
        ),
        user_prompt_template=(
            "基于以下 {article_count} 篇综合文章，生成当日综合早报摘要：\n\n{articles}"
        ),
    ),
}


def get_template(category: str) -> BriefingTemplate:
    """Get the briefing template for a category.

    Args:
        category: One of {finance, tech, ai, general}.

    Returns:
        BriefingTemplate for the category.

    Raises:
        KeyError: If category is not in BRIEFING_TEMPLATES (Rule 12 — fail
            loud rather than returning a default that may mask a bug).
    """
    return BRIEFING_TEMPLATES[category]


__all__ = [
    "BRIEFING_TEMPLATES",
    "BriefingTemplate",
    "get_template",
]

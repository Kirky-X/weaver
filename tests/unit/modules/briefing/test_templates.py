# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for briefing category templates (T008 / R-briefing-003).

Verifies 4 category templates (finance/tech/ai/general) are defined with:
- system_prompt: emphasizing category-specific focus
- user_prompt_template: containing {articles} placeholder

Templates are declarative data (R-briefing-003). T008 generate_briefing
reuses BriefingGenerator's generic briefing.toml prompt; templates will
be consumed by T021+ narrative mode (category-specific prompt injection).
"""

from __future__ import annotations

import pytest

from modules.briefing.templates import (
    BRIEFING_TEMPLATES,
    BriefingTemplate,
    get_template,
)


class TestTemplateDefinition:
    """Verify 4 category templates are defined (R-briefing-003)."""

    def test_all_4_categories_defined(self) -> None:
        """Templates MUST be defined for finance/tech/ai/general."""
        expected = {"finance", "tech", "ai", "general"}
        assert set(BRIEFING_TEMPLATES.keys()) == expected, (
            f"Expected {expected}, got {set(BRIEFING_TEMPLATES.keys())}"
        )

    def test_finance_template_emphasizes_financial_terminology(self) -> None:
        """R-briefing-003: finance template emphasizes 金融术语准确性."""
        template = BRIEFING_TEMPLATES["finance"]
        assert isinstance(template, BriefingTemplate)
        # System prompt must mention finance/financial focus
        prompt_lower = template.system_prompt.lower()
        assert any(kw in prompt_lower for kw in ["金融", "财经", "financial", "finance"]), (
            f"finance system_prompt must mention financial focus, got: {template.system_prompt}"
        )

    def test_tech_template_emphasizes_technical_details(self) -> None:
        """R-briefing-003: tech template emphasizes 技术细节."""
        template = BRIEFING_TEMPLATES["tech"]
        prompt_lower = template.system_prompt.lower()
        assert any(kw in prompt_lower for kw in ["技术", "科技", "technical", "tech"]), (
            f"tech system_prompt must mention technical focus, got: {template.system_prompt}"
        )

    def test_ai_template_emphasizes_models_algorithms(self) -> None:
        """R-briefing-003: ai template emphasizes 模型/算法."""
        template = BRIEFING_TEMPLATES["ai"]
        prompt_lower = template.system_prompt.lower()
        assert any(
            kw in prompt_lower for kw in ["模型", "算法", "人工智能", "ai", "model", "algorithm"]
        ), f"ai system_prompt must mention AI/model focus, got: {template.system_prompt}"

    def test_general_template_emphasizes_breadth_coverage(self) -> None:
        """R-briefing-003: general template emphasizes 广度覆盖."""
        template = BRIEFING_TEMPLATES["general"]
        prompt_lower = template.system_prompt.lower()
        assert any(
            kw in prompt_lower
            for kw in ["综合", "广度", "全面", "general", "broad", "comprehensive"]
        ), f"general system_prompt must mention breadth, got: {template.system_prompt}"


class TestTemplateUserPrompt:
    """Verify user_prompt_template has {articles} placeholder (R-briefing-003)."""

    @pytest.mark.parametrize("category", ["finance", "tech", "ai", "general"])
    def test_user_prompt_template_has_articles_placeholder(self, category: str) -> None:
        """Each template's user_prompt_template MUST contain {articles} placeholder."""
        template = BRIEFING_TEMPLATES[category]
        assert "{articles}" in template.user_prompt_template, (
            f"{category} user_prompt_template must contain {{articles}} placeholder, "
            f"got: {template.user_prompt_template}"
        )


class TestGetTemplate:
    """Verify get_template() lookup function."""

    @pytest.mark.parametrize("category", ["finance", "tech", "ai", "general"])
    def test_get_template_returns_correct_template(self, category: str) -> None:
        """get_template(category) returns the matching BriefingTemplate."""
        template = get_template(category)
        assert template is BRIEFING_TEMPLATES[category]

    def test_get_template_raises_key_error_for_invalid_category(self) -> None:
        """get_template raises KeyError for unknown category (Rule 12: fail loud)."""
        with pytest.raises(KeyError):
            get_template("sports")


class TestBriefingTemplateDataclass:
    """Verify BriefingTemplate dataclass shape."""

    def test_is_dataclass(self) -> None:
        from dataclasses import is_dataclass

        assert is_dataclass(BriefingTemplate)

    def test_has_system_prompt_and_user_prompt_template_fields(self) -> None:
        from dataclasses import fields

        field_names = {f.name for f in fields(BriefingTemplate)}
        assert {"system_prompt", "user_prompt_template"}.issubset(field_names)

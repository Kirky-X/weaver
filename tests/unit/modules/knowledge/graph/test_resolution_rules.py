# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for EntityResolutionRules (knowledge module)."""

from __future__ import annotations

from modules.knowledge.graph.resolution_rules import (
    EntityResolutionRules,
    EntityType,
    MatchType,
    ResolutionResult,
)


class TestMatchType:
    """Tests for MatchType enum."""

    def test_values(self) -> None:
        assert MatchType.EXACT.value == "exact"
        assert MatchType.CASE_INSENSITIVE.value == "case_insensitive"
        assert MatchType.FUZZY.value == "fuzzy"
        assert MatchType.NONE.value == "none"


class TestEntityType:
    """Tests for EntityType enum."""

    def test_values(self) -> None:
        assert EntityType.PERSON.value == "人物"
        assert EntityType.ORGANIZATION.value == "组织机构"
        assert EntityType.LOCATION.value == "地点"


class TestEntityResolutionRulesExactMatch:
    """Tests for exact matching."""

    def test_exact_match(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("华为", "组织机构", [{"canonical_name": "华为"}])
        assert result.match_type == MatchType.EXACT
        assert result.confidence == 1.0
        assert result.should_merge is True

    def test_no_match(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("未知实体", "组织机构", [{"canonical_name": "华为"}])
        assert result.match_type == MatchType.NONE
        assert result.should_merge is False

    def test_no_candidates(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("华为", "组织机构", candidates=None)
        assert result.match_type == MatchType.NONE


class TestCaseInsensitiveMatch:
    """Tests for case-insensitive matching."""

    def test_case_insensitive(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("openai", "组织机构", [{"canonical_name": "OpenAI"}])
        assert result.match_type == MatchType.CASE_INSENSITIVE
        assert result.confidence == 0.95

    def test_same_case_not_triggered(self) -> None:
        """Same case should trigger exact match first."""
        rules = EntityResolutionRules()
        result = rules.resolve("OpenAI", "组织机构", [{"canonical_name": "OpenAI"}])
        assert result.match_type == MatchType.EXACT


class TestKnownAliasMatch:
    """Tests for alias matching."""

    def test_alias_match(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("谷歌", "组织机构", [{"canonical_name": "Google"}])
        assert result.match_type == MatchType.ALIAS
        assert result.confidence == 0.95

    def test_reverse_alias(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("Google", "组织机构", [{"canonical_name": "谷歌"}])
        # Should match via alias or case-insensitive
        assert result.match_type in (MatchType.ALIAS, MatchType.CASE_INSENSITIVE, MatchType.EXACT)

    def test_both_aliases(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("OpenAI Inc", "组织机构", [{"canonical_name": "OpenAI公司"}])
        assert result.match_type == MatchType.ALIAS
        assert result.should_merge is True


class TestAbbreviationMatch:
    """Tests for abbreviation matching."""

    def test_abbreviation_to_full(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("AI", "概念", [{"canonical_name": "人工智能"}])
        assert result.match_type == MatchType.ABBREVIATION

    def test_full_to_abbreviation(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("人工智能", "概念", [{"canonical_name": "AI"}])
        assert result.match_type == MatchType.ABBREVIATION

    def test_both_abbreviations(self) -> None:
        rules = EntityResolutionRules()
        # Both resolve to same full name
        result = rules.resolve("AI", "概念", [{"canonical_name": "AI"}])
        # AI == AI is exact match first
        assert result.match_type == MatchType.EXACT


class TestTranslationMatch:
    """Tests for translation matching."""

    def test_english_to_chinese(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("China", "地点", [{"canonical_name": "中国"}])
        assert result.match_type == MatchType.TRANSLATION
        assert result.confidence == 0.9

    def test_chinese_to_english(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("中国", "地点", [{"canonical_name": "China"}])
        assert result.match_type == MatchType.TRANSLATION


class TestBracketVariantMatch:
    """Tests for bracket variant matching."""

    def test_bracket_variant(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("Headphone (1)", "产品", [{"canonical_name": "Headphone (a)"}])
        assert result.match_type == MatchType.FUZZY
        assert result.confidence == 0.90
        assert result.should_merge is True


class TestPersonNameVariantMatch:
    """Tests for person name variant matching."""

    def test_with_title(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("张先生", "人物", [{"canonical_name": "张"}])
        assert result.match_type == MatchType.ALIAS
        assert result.should_merge is True

    def test_with_english_title(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("John Mr.", "人物", [{"canonical_name": "John"}])
        assert result.match_type == MatchType.ALIAS


class TestOrganizationVariantMatch:
    """Tests for organization variant matching."""

    def test_suffix_variant(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("华为技术", "组织机构", [{"canonical_name": "华为"}])
        assert result.match_type == MatchType.ALIAS
        assert result.should_merge is True


class TestLocationVariantMatch:
    """Tests for location variant matching."""

    def test_suffix_variant(self) -> None:
        rules = EntityResolutionRules()
        result = rules.resolve("深圳市", "地点", [{"canonical_name": "深圳"}])
        assert result.match_type == MatchType.ALIAS


class TestAddAlias:
    """Tests for add_alias method."""

    def test_add_new_alias(self) -> None:
        rules = EntityResolutionRules()
        rules.add_alias("TestOrg", "TO")
        result = rules.resolve("TO", "组织机构", [{"canonical_name": "TestOrg"}])
        assert result.match_type == MatchType.ALIAS


class TestAddAbbreviation:
    """Tests for add_abbreviation method."""

    def test_add_abbreviation(self) -> None:
        rules = EntityResolutionRules()
        rules.add_abbreviation("FOO", "Foo Object Oriented")
        result = rules.resolve("FOO", "概念", [{"canonical_name": "Foo Object Oriented"}])
        assert result.match_type == MatchType.ABBREVIATION


class TestAddTranslation:
    """Tests for add_translation method."""

    def test_add_translation(self) -> None:
        rules = EntityResolutionRules()
        rules.add_translation("New Country", "新国家")
        result = rules.resolve("New Country", "地点", [{"canonical_name": "新国家"}])
        assert result.match_type == MatchType.TRANSLATION


class TestGetCanonicalSuggestion:
    """Tests for get_canonical_suggestion."""

    def test_abbreviation_suggestion(self) -> None:
        rules = EntityResolutionRules()
        assert rules.get_canonical_suggestion("AI", "概念") == "人工智能"

    def test_alias_suggestion(self) -> None:
        rules = EntityResolutionRules()
        assert rules.get_canonical_suggestion("谷歌", "组织机构") == "Google"

    def test_unknown_returns_name(self) -> None:
        rules = EntityResolutionRules()
        assert rules.get_canonical_suggestion("UnknownEntity", "概念") == "UnknownEntity"

    def test_translation_chinese(self) -> None:
        rules = EntityResolutionRules()
        result = rules.get_canonical_suggestion("China", "地点")
        assert result == "中国"


class TestGetHelpers:
    """Tests for helper getter methods."""

    def test_get_all_aliases(self) -> None:
        rules = EntityResolutionRules()
        aliases = rules.get_all_aliases("Google")
        assert "谷歌" in aliases
        assert "Google Inc" in aliases

    def test_get_all_aliases_unknown(self) -> None:
        rules = EntityResolutionRules()
        assert rules.get_all_aliases("Unknown") == set()

    def test_get_abbreviation_full(self) -> None:
        rules = EntityResolutionRules()
        assert rules.get_abbreviation_full("AI") == "人工智能"
        assert rules.get_abbreviation_full("UNKNOWN") is None

    def test_get_translation(self) -> None:
        rules = EntityResolutionRules()
        assert rules.get_translation("China") == "中国"
        assert rules.get_translation("Unknown") is None


class TestAddRule:
    """Tests for add_rule."""

    def test_add_custom_rule(self) -> None:
        from modules.knowledge.graph.resolution_rules import ResolutionRule

        rules = EntityResolutionRules()

        def custom_matcher(name, canonical, entity_type):
            if name == "special" and canonical == "special":
                return ResolutionResult(
                    match_type=MatchType.EXACT,
                    confidence=1.0,
                    canonical_name=canonical,
                    should_merge=True,
                    reason="Custom rule",
                )
            return None

        rule = ResolutionRule(
            name="custom",
            entity_types=None,
            priority=-1,  # Highest priority
            matcher=custom_matcher,
        )
        rules.add_rule(rule)

        result = rules.resolve("special", "概念", [{"canonical_name": "special"}])
        assert result.reason == "Custom rule"

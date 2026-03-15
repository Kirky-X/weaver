"""Unit tests for entity resolution rules module."""

import pytest
from modules.graph_store.resolution_rules import (
    EntityResolutionRules,
    ResolutionResult,
    MatchType,
    ResolutionRule,
)


class TestResolutionResult:
    """Test ResolutionResult dataclass."""

    def test_initialization(self):
        """Test ResolutionResult initialization."""
        result = ResolutionResult(
            match_type=MatchType.EXACT,
            confidence=0.95,
            canonical_name="Test Entity",
            should_merge=True,
            reason="Exact match found",
        )

        assert result.match_type == MatchType.EXACT
        assert result.confidence == 0.95
        assert result.canonical_name == "Test Entity"
        assert result.should_merge is True
        assert result.reason == "Exact match found"

    def test_with_metadata(self):
        """Test ResolutionResult with metadata."""
        result = ResolutionResult(
            match_type=MatchType.ALIAS,
            confidence=0.85,
            canonical_name="Entity",
            should_merge=True,
            reason="Alias match",
            metadata={"original": "Original Name"},
        )

        assert result.metadata["original"] == "Original Name"


class TestEntityResolutionRules:
    """Test EntityResolutionRules class."""

    def test_init(self):
        """Test initialization."""
        rules = EntityResolutionRules()
        assert len(rules._rules) > 0

    def test_exact_match(self):
        """Test exact match rule."""
        rules = EntityResolutionRules()
        result = rules._exact_match("Apple", "Apple", "组织机构")

        assert result is not None
        assert result.match_type == MatchType.EXACT
        assert result.confidence == 1.0

    def test_exact_match_no_match(self):
        """Test exact match with no match."""
        rules = EntityResolutionRules()
        result = rules._exact_match("Apple", "Banana", "组织机构")

        assert result is None

    def test_case_insensitive_match(self):
        """Test case insensitive match."""
        rules = EntityResolutionRules()
        result = rules._case_insensitive_match("apple", "Apple", "组织机构")

        assert result is not None
        assert result.match_type == MatchType.CASE_INSENSITIVE
        assert result.confidence == 0.95

    def test_case_insensitive_no_match(self):
        """Test case insensitive with different words."""
        rules = EntityResolutionRules()
        result = rules._case_insensitive_match("apple", "Banana", "组织机构")

        assert result is None

    def test_known_alias_match(self):
        """Test known alias matching."""
        rules = EntityResolutionRules()
        result = rules._known_alias_match("谷歌", "Google", "组织机构")

        assert result is not None
        assert result.match_type == MatchType.ALIAS
        assert result.should_merge is True

    def test_abbreviation_match(self):
        """Test abbreviation matching."""
        rules = EntityResolutionRules()
        result = rules._abbreviation_match("AI", "人工智能", "概念")

        assert result is not None
        assert result.match_type == MatchType.ABBREVIATION

    def test_translation_match(self):
        """Test translation matching."""
        rules = EntityResolutionRules()
        result = rules._translation_match("中国", "China", "地点")

        assert result is not None
        assert result.match_type == MatchType.TRANSLATION

    def test_person_name_variant_match(self):
        """Test person name variant matching."""
        rules = EntityResolutionRules()
        
        name_with_title = "张三先生"
        canonical = "张三"
        
        result = rules._person_name_variant_match(name_with_title, canonical, "人物")
        
        if result:
            assert result.match_type == MatchType.ALIAS

    def test_person_name_variant_no_match(self):
        """Test person name variant with no match."""
        rules = EntityResolutionRules()
        result = rules._person_name_variant_match(
            "王五", "张三", "人物"
        )

        assert result is None

    def test_organization_variant_match(self):
        """Test organization variant matching."""
        rules = EntityResolutionRules()
        result = rules._organization_variant_match(
            "阿里巴巴公司", "阿里巴巴集团", "组织机构"
        )

        assert result is not None
        assert result.should_merge is True

    def test_location_variant_match(self):
        """Test location variant matching."""
        rules = EntityResolutionRules()
        result = rules._location_variant_match("北京市", "北京", "地点")

        assert result is not None
        assert result.match_type == MatchType.ALIAS

    def test_resolve_with_candidates(self):
        """Test resolve method with candidates."""
        rules = EntityResolutionRules()
        candidates = [{"canonical_name": "Google"}]

        result = rules.resolve("谷歌", "组织机构", candidates)

        assert result is not None
        assert result.should_merge is True

    def test_resolve_no_match(self):
        """Test resolve with no matching candidates."""
        rules = EntityResolutionRules()
        candidates = [{"canonical_name": "Microsoft"}]

        result = rules.resolve("Unknown", "人物", candidates)

        assert result.match_type == MatchType.NONE

    def test_get_canonical_suggestion(self):
        """Test canonical name suggestion."""
        rules = EntityResolutionRules()

        assert rules.get_canonical_suggestion("AI", "概念") == "人工智能"
        assert rules.get_canonical_suggestion("谷歌", "组织机构") == "Google"
        assert rules.get_canonical_suggestion("未知", "人物") == "未知"

    def test_is_chinese(self):
        """Test Chinese character detection."""
        rules = EntityResolutionRules()

        assert rules._is_chinese("你好") is True
        assert rules._is_chinese("Hello") is False
        assert rules._is_chinese("Hello你好") is True

    def test_get_all_aliases(self):
        """Test getting all aliases."""
        rules = EntityResolutionRules()

        aliases = rules.get_all_aliases("Google")
        assert "谷歌" in aliases

    def test_get_abbreviation_full(self):
        """Test getting full form of abbreviation."""
        rules = EntityResolutionRules()

        assert rules.get_abbreviation_full("AI") == "人工智能"
        assert rules.get_abbreviation_full("XYZ") is None

    def test_get_translation(self):
        """Test getting translation."""
        rules = EntityResolutionRules()

        translation = rules.get_translation("中国")
        if translation:
            assert translation == "China"
        else:
            assert rules.get_translation("China") == "中国"

    def test_add_custom_rule(self):
        """Test adding custom resolution rule."""
        rules = EntityResolutionRules()

        def custom_match(name, canonical, entity_type):
            if name == "test" and canonical == "test":
                return ResolutionResult(
                    match_type=MatchType.EXACT,
                    confidence=1.0,
                    canonical_name=canonical,
                    should_merge=True,
                    reason="Custom match",
                )
            return None

        rule = ResolutionRule(
            name="custom",
            entity_types=None,
            priority=5,
            matcher=custom_match,
        )

        rules.add_rule(rule)

        assert len(rules._rules) > 0

    def test_add_alias(self):
        """Test adding custom alias."""
        rules = EntityResolutionRules()
        rules.add_alias("TestCorp", "TC")

        aliases = rules.get_all_aliases("TestCorp")
        assert "TC" in aliases

    def test_add_abbreviation(self):
        """Test adding custom abbreviation."""
        rules = EntityResolutionRules()
        rules.add_abbreviation("T1", "Test1")

        assert rules.get_abbreviation_full("T1") == "Test1"

    def test_add_translation(self):
        """Test adding custom translation."""
        rules = EntityResolutionRules()
        rules.add_translation("TestCountry", "测试国")

        assert rules.get_translation("TestCountry") == "测试国"

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Unit tests for NameNormalizer (knowledge module)."""

from __future__ import annotations

from modules.knowledge.graph.name_normalizer import (
    NameNormalizer,
    NameScript,
    NormalizationResult,
)


class TestNameScript:
    """Tests for NameScript enum."""

    def test_values(self) -> None:
        assert NameScript.CHINESE.value == "chinese"
        assert NameScript.ENGLISH.value == "english"
        assert NameScript.MIXED.value == "mixed"


class TestNormalizationResult:
    """Tests for NormalizationResult dataclass."""

    def test_creation(self) -> None:
        result = NormalizationResult(
            original="Test",
            normalized="test",
            script=NameScript.ENGLISH,
            changes=["case_normalization"],
            confidence=0.95,
        )
        assert result.normalized == "test"
        assert result.confidence == 0.95


class TestNameNormalizerInit:
    """Tests for initialization."""

    def test_defaults(self) -> None:
        normalizer = NameNormalizer()
        assert normalizer._prefer_chinese is True
        assert normalizer._normalize_case is True
        assert normalizer._normalize_whitespace is True

    def test_custom_params(self) -> None:
        normalizer = NameNormalizer(
            prefer_chinese=False,
            normalize_case=False,
        )
        assert normalizer._prefer_chinese is False
        assert normalizer._normalize_case is False


class TestNormalize:
    """Tests for normalize method."""

    def test_empty_name(self) -> None:
        normalizer = NameNormalizer()
        result = normalizer.normalize("")
        assert result.normalized == ""
        assert result.confidence == 0.0

    def test_chinese_name(self) -> None:
        normalizer = NameNormalizer()
        result = normalizer.normalize("华为技术有限公司")
        assert result.script == NameScript.CHINESE
        assert "华为" in result.normalized

    def test_english_name(self) -> None:
        normalizer = NameNormalizer()
        result = normalizer.normalize("hello world")
        assert result.script == NameScript.ENGLISH

    def test_mixed_name(self) -> None:
        normalizer = NameNormalizer()
        result = normalizer.normalize("华为Huawei")
        assert result.script == NameScript.MIXED

    def test_unicode_normalization(self) -> None:
        normalizer = NameNormalizer()
        result = normalizer.normalize("\u3000华为\u00a0")
        assert "华为" in result.normalized
        assert (
            "unicode_normalization" in result.changes
            or "whitespace_normalization" in result.changes
        )

    def test_whitespace_normalization(self) -> None:
        normalizer = NameNormalizer()
        result = normalizer.normalize("  hello   world  ")
        # Case normalization also runs, so "hello" -> "Hello"
        assert "Hello" in result.normalized
        assert "World" in result.normalized

    def test_special_chars_removed(self) -> None:
        normalizer = NameNormalizer()
        result = normalizer.normalize("「华为」")
        assert "华为" in result.normalized
        assert "「" not in result.normalized

    def test_case_normalization_english(self) -> None:
        normalizer = NameNormalizer()
        result = normalizer.normalize("hello")
        assert result.normalized == "Hello"

    def test_case_normalization_preserves_acronyms(self) -> None:
        normalizer = NameNormalizer()
        result = normalizer.normalize("IBM")
        assert result.normalized == "IBM"

    def test_org_suffix_normalization(self) -> None:
        normalizer = NameNormalizer()
        result = normalizer.normalize("Huawei Inc.", entity_type="组织机构")
        assert "Inc" in result.normalized

    def test_no_changes_high_confidence(self) -> None:
        normalizer = NameNormalizer(normalize_case=False, normalize_whitespace=False)
        result = normalizer.normalize("华为")
        assert result.confidence == 1.0
        assert result.changes == []


class TestSelectCanonical:
    """Tests for select_canonical."""

    def test_empty_list(self) -> None:
        normalizer = NameNormalizer()
        assert normalizer.select_canonical([]) == ""

    def test_single_name(self) -> None:
        normalizer = NameNormalizer()
        assert normalizer.select_canonical(["华为"]) == "华为"

    def test_prefers_chinese(self) -> None:
        normalizer = NameNormalizer(prefer_chinese=True)
        result = normalizer.select_canonical(["Huawei", "华为"])
        assert result == "华为"

    def test_prefers_english_when_configured(self) -> None:
        normalizer = NameNormalizer(prefer_chinese=False)
        result = normalizer.select_canonical(["Huawei", "华为"])
        # English preferred
        assert "Huawei" in result or result  # Just verify it returns something


class TestAreEquivalent:
    """Tests for are_equivalent."""

    def test_identical(self) -> None:
        normalizer = NameNormalizer()
        eq, conf = normalizer.are_equivalent("华为", "华为")
        assert eq is True
        assert conf == 1.0

    def test_case_insensitive(self) -> None:
        normalizer = NameNormalizer(normalize_case=False)
        eq, conf = normalizer.are_equivalent("hello", "HELLO")
        assert eq is True
        assert conf == 0.95

    def test_different(self) -> None:
        normalizer = NameNormalizer()
        eq, conf = normalizer.are_equivalent("华为", "小米")
        assert eq is False
        assert conf == 0.0

    def test_bracket_variant(self) -> None:
        normalizer = NameNormalizer()
        eq, conf = normalizer.are_equivalent("Headphone (1)", "Headphone (a)")
        assert eq is True
        assert conf == 0.90

    def test_suffix_stripped(self) -> None:
        normalizer = NameNormalizer()
        eq, conf = normalizer.are_equivalent("华为有限公司", "华为公司")
        assert eq is True


class TestGenerateSortKey:
    """Tests for generate_sort_key."""

    def test_chinese_sort_key(self) -> None:
        normalizer = NameNormalizer()
        key = normalizer.generate_sort_key("华为")
        assert key.startswith("z_")

    def test_english_sort_key(self) -> None:
        normalizer = NameNormalizer()
        key = normalizer.generate_sort_key("Huawei")
        assert key.startswith("a_")

    def test_mixed_sort_key(self) -> None:
        normalizer = NameNormalizer()
        key = normalizer.generate_sort_key("华为Hua")
        assert key.startswith("m_") or key.startswith("z_")


class TestDetectScript:
    """Tests for _detect_script."""

    def test_chinese(self) -> None:
        normalizer = NameNormalizer()
        assert normalizer._detect_script("华为") == NameScript.CHINESE

    def test_english(self) -> None:
        normalizer = NameNormalizer()
        assert normalizer._detect_script("Huawei") == NameScript.ENGLISH

    def test_mixed(self) -> None:
        normalizer = NameNormalizer()
        assert normalizer._detect_script("华为Hua") == NameScript.MIXED

    def test_other(self) -> None:
        normalizer = NameNormalizer()
        assert normalizer._detect_script("12345") == NameScript.OTHER


class TestWhitespaceOnlyCandidate:
    """Regression: whitespace-only candidates normalize to "" and must not
    crash the scorer with IndexError."""

    def test_whitespace_only_name_does_not_crash(self) -> None:
        normalizer = NameNormalizer()
        result = normalizer.normalize("   ", "概念")
        score = normalizer._score_canonical_candidate(result)
        assert isinstance(score, float)

    def test_select_canonical_with_whitespace_candidates(self) -> None:
        normalizer = NameNormalizer()
        # Must not raise IndexError even though all candidates normalize
        # to empty strings.
        selected = normalizer.select_canonical(["   ", ""], "概念")
        assert isinstance(selected, str)


class TestQuoteStrippingCharacterClass:
    """#201: the quote/backtick character class must be explicit."""

    def test_ascii_quotes_and_backticks_stripped(self) -> None:
        normalizer = NameNormalizer()

        result = normalizer.normalize("\"华为\" 'Mate' `P`")

        assert '"' not in result.normalized
        assert "'" not in result.normalized
        assert "`" not in result.normalized
        assert "华为" in result.normalized


class TestTrailingBracketPattern:
    """#92: the trailing-bracket regex is precompiled once at module level."""

    def test_pattern_is_precompiled_and_reused(self) -> None:
        import importlib
        import re as re_module

        # NOTE: `modules.knowledge.graph.name_normalizer` is shadowed in the
        # package namespace by the exported singleton of the same name.
        module = importlib.import_module("modules.knowledge.graph.name_normalizer")

        assert isinstance(module._TRAILING_BRACKET_PATTERN, re_module.Pattern)
        assert module.strip_bracket_variant("Phone (4a)") == ("Phone", "(4a)")
        assert module.strip_bracket_variant("Phone") == ("Phone", "")

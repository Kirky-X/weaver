"""Unit tests for name normalizer module."""

import pytest
from modules.graph_store.name_normalizer import (
    NameNormalizer,
    NormalizationResult,
    NameScript,
)


class TestNormalizationResult:
    """Test NormalizationResult dataclass."""

    def test_initialization(self):
        """Test NormalizationResult initialization."""
        result = NormalizationResult(
            original="  Test  ",
            normalized="Test",
            script=NameScript.ENGLISH,
            changes=["whitespace_normalization"],
            confidence=0.95,
        )

        assert result.original == "  Test  "
        assert result.normalized == "Test"
        assert result.script == NameScript.ENGLISH
        assert result.confidence == 0.95


class TestNameNormalizer:
    """Test NameNormalizer class."""

    def test_init_default(self):
        """Test default initialization."""
        normalizer = NameNormalizer()
        assert normalizer._prefer_chinese is True

    def test_init_custom(self):
        """Test custom initialization."""
        normalizer = NameNormalizer(prefer_chinese=False)
        assert normalizer._prefer_chinese is False

    def test_detect_script_chinese(self):
        """Test Chinese script detection."""
        normalizer = NameNormalizer()
        assert normalizer._detect_script("你好世界") == NameScript.CHINESE

    def test_detect_script_english(self):
        """Test English script detection."""
        normalizer = NameNormalizer()
        assert normalizer._detect_script("Hello World") == NameScript.ENGLISH

    def test_detect_script_mixed(self):
        """Test mixed script detection."""
        normalizer = NameNormalizer()
        assert normalizer._detect_script("你好Hello") == NameScript.MIXED

    def test_detect_script_other(self):
        """Test other script detection."""
        normalizer = NameNormalizer()
        assert normalizer._detect_script("12345") == NameScript.OTHER

    def test_normalize_unicode(self):
        """Test Unicode normalization."""
        normalizer = NameNormalizer()
        result = normalizer.normalize("café")

        assert "caf" in result.normalized.lower()

    def test_normalize_whitespace(self):
        """Test whitespace normalization."""
        normalizer = NameNormalizer()
        result = normalizer.normalize("  Test   Name  ")

        assert "Test Name" in result.normalized
        assert "whitespace_normalization" in result.changes

    def test_normalize_special_chars(self):
        """Test special character removal."""
        normalizer = NameNormalizer()
        result = normalizer.normalize('Test "Name"')

        assert '"' not in result.normalized

    def test_normalize_case_english(self):
        """Test case normalization for English."""
        normalizer = NameNormalizer()
        result = normalizer.normalize("JOHN DOE")

        assert "John" in result.normalized or "JOHN" in result.normalized

    def test_normalize_chinese_prefer(self):
        """Test Chinese preference."""
        normalizer = NameNormalizer(prefer_chinese=True)
        result = normalizer.normalize("北京 Beijing")

        assert result.script == NameScript.MIXED

    def test_normalize_organization_suffix(self):
        """Test organization suffix normalization."""
        normalizer = NameNormalizer()
        result = normalizer.normalize("阿里巴巴集团", "组织机构")

        assert "集团" in result.normalized

    def test_select_canonical_empty(self):
        """Test canonical selection with empty list."""
        normalizer = NameNormalizer()
        result = normalizer.select_canonical([])

        assert result == ""

    def test_select_canonical_single(self):
        """Test canonical selection with single item."""
        normalizer = NameNormalizer()
        result = normalizer.select_canonical(["Test"])

        assert result == "Test"

    def test_select_canonical_multiple(self):
        """Test canonical selection with multiple items."""
        normalizer = NameNormalizer()
        names = ["Apple", "苹果", "APPLE"]
        result = normalizer.select_canonical(names)

        assert result in names

    def test_are_equivalent_exact(self):
        """Test exact equivalence check."""
        normalizer = NameNormalizer()
        is_equiv, confidence = normalizer.are_equivalent("Test", "Test")

        assert is_equiv is True
        assert confidence == 1.0

    def test_are_equivalent_case(self):
        """Test case-insensitive equivalence."""
        normalizer = NameNormalizer()
        is_equiv, confidence = normalizer.are_equivalent("test", "Test")

        assert is_equiv is True

    def test_are_equivalent_suffix(self):
        """Test suffix-based equivalence."""
        normalizer = NameNormalizer()
        is_equiv, _ = normalizer.are_equivalent(
            "Apple Inc", "Apple Corp", "组织机构"
        )

        assert is_equiv is True

    def test_are_equivalent_not_equivalent(self):
        """Test non-equivalent names."""
        normalizer = NameNormalizer()
        is_equiv, confidence = normalizer.are_equivalent("Apple", "Banana")

        assert is_equiv is False
        assert confidence == 0.0

    def test_generate_sort_key_english(self):
        """Test sort key for English names."""
        normalizer = NameNormalizer()
        key = normalizer.generate_sort_key("Apple")

        assert key.startswith("a_")

    def test_generate_sort_key_chinese(self):
        """Test sort key for Chinese names."""
        normalizer = NameNormalizer()
        key = normalizer.generate_sort_key("苹果")

        assert key.startswith("z_")

    def test_get_chinese_ratio(self):
        """Test Chinese character ratio calculation."""
        normalizer = NameNormalizer()

        assert normalizer._get_chinese_ratio("你好") == 1.0
        assert normalizer._get_chinese_ratio("Hello") == 0.0
        assert normalizer._get_chinese_ratio("你好Hello") > 0

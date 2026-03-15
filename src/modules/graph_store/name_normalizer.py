"""Entity name normalization for consistent canonical name selection.

Provides comprehensive name normalization including:
- Unicode normalization
- Whitespace normalization
- Case normalization for English names
- Chinese/English name preference
- Special character handling
- Organization suffix normalization
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.observability.logging import get_logger

log = get_logger("entity.name_normalizer")


class NameScript(Enum):
    """Script type of the name."""

    CHINESE = "chinese"
    ENGLISH = "english"
    MIXED = "mixed"
    OTHER = "other"


@dataclass
class NormalizationResult:
    """Result of name normalization."""

    original: str
    normalized: str
    script: NameScript
    changes: list[str]
    confidence: float


class NameNormalizer:
    """Entity name normalizer for consistent canonical name selection.

    This normalizer applies a series of transformations to produce
    a canonical form suitable for entity deduplication.
    """

    def __init__(
        self,
        prefer_chinese: bool = True,
        normalize_case: bool = True,
        normalize_whitespace: bool = True,
        remove_special_chars: bool = True,
        normalize_org_suffixes: bool = True,
    ) -> None:
        """Initialize the name normalizer.

        Args:
            prefer_chinese: Whether to prefer Chinese names over English.
            normalize_case: Whether to normalize case for English names.
            normalize_whitespace: Whether to normalize whitespace.
            remove_special_chars: Whether to remove special characters.
            normalize_org_suffixes: Whether to normalize organization suffixes.
        """
        self._prefer_chinese = prefer_chinese
        self._normalize_case = normalize_case
        self._normalize_whitespace = normalize_whitespace
        self._remove_special_chars = remove_special_chars
        self._normalize_org_suffixes = normalize_org_suffixes

        self._org_suffix_map = {
            "Inc.": "Inc",
            "Inc": "Inc",
            "Corp.": "Corp",
            "Corp": "Corp",
            "Ltd.": "Ltd",
            "Ltd": "Ltd",
            "LLC": "LLC",
            "Co.": "Co",
            "Co": "Co",
            "Corporation": "Corp",
            "Incorporated": "Inc",
            "Limited": "Ltd",
            "GmbH": "GmbH",
            "AG": "AG",
            "SA": "SA",
        }

        self._chinese_org_suffixes = [
            "有限公司", "股份有限公司", "集团", "公司",
            "科技", "技术", "网络", "信息", "互联网",
        ]

    def normalize(
        self,
        name: str,
        entity_type: str | None = None,
    ) -> NormalizationResult:
        """Normalize an entity name.

        Args:
            name: The entity name to normalize.
            entity_type: Optional entity type for type-specific normalization.

        Returns:
            NormalizationResult with normalized name and metadata.
        """
        if not name:
            return NormalizationResult(
                original=name,
                normalized="",
                script=NameScript.OTHER,
                changes=["empty_name"],
                confidence=0.0,
            )

        original = name
        changes = []
        script = self._detect_script(name)

        name = self._normalize_unicode(name)
        if name != original:
            changes.append("unicode_normalization")

        if self._normalize_whitespace:
            name = self._normalize_whitespace_chars(name)
            if name != original and "whitespace_normalization" not in changes:
                changes.append("whitespace_normalization")

        if self._remove_special_chars:
            prev = name
            name = self._remove_special(name)
            if name != prev:
                changes.append("special_chars_removed")

        if self._normalize_case and script in (NameScript.ENGLISH, NameScript.MIXED):
            prev = name
            name = self._normalize_case_for_english(name)
            if name != prev:
                changes.append("case_normalization")

        if self._normalize_org_suffixes and entity_type == "组织机构":
            prev = name
            name = self._normalize_organization_suffix(name)
            if name != prev:
                changes.append("org_suffix_normalization")

        name = name.strip()

        confidence = 1.0 if not changes else 0.95

        return NormalizationResult(
            original=original,
            normalized=name,
            script=script,
            changes=changes,
            confidence=confidence,
        )

    def _detect_script(self, text: str) -> NameScript:
        """Detect the primary script of the text."""
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text))
        has_english = bool(re.search(r'[a-zA-Z]', text))

        if has_chinese and has_english:
            return NameScript.MIXED
        elif has_chinese:
            return NameScript.CHINESE
        elif has_english:
            return NameScript.ENGLISH
        else:
            return NameScript.OTHER

    def _normalize_unicode(self, text: str) -> str:
        """Normalize Unicode characters."""
        text = unicodedata.normalize('NFKC', text)
        text = text.replace('\u3000', ' ')
        text = text.replace('\u00a0', ' ')
        return text

    def _normalize_whitespace_chars(self, text: str) -> str:
        """Normalize whitespace characters."""
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'^\s+|\s+$', '', text)
        return text

    def _remove_special(self, text: str) -> str:
        """Remove special characters while preserving meaningful ones."""
        text = re.sub(r'["""\'\'`]', '', text)
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        text = re.sub(r'\s*[-–—]\s*', '-', text)
        return text

    def _normalize_case_for_english(self, text: str) -> str:
        """Normalize case for English text.

        For mixed Chinese-English text, only normalize the English parts.
        """
        def normalize_english_part(match):
            word = match.group(0)
            if word.isupper() and len(word) <= 4:
                return word
            if word.islower():
                return word.capitalize()
            return word

        text = re.sub(r'[A-Za-z]+', normalize_english_part, text)
        return text

    def _normalize_organization_suffix(self, name: str) -> str:
        """Normalize organization suffixes."""
        for suffix, normalized in self._org_suffix_map.items():
            pattern = rf'\s+{re.escape(suffix)}\.?$'
            if re.search(pattern, name, re.IGNORECASE):
                name = re.sub(pattern, f' {normalized}', name, flags=re.IGNORECASE)
                break

        for suffix in self._chinese_org_suffixes:
            if name.endswith(suffix) and len(name) > len(suffix) + 2:
                pass

        return name

    def select_canonical(
        self,
        names: list[str],
        entity_type: str | None = None,
    ) -> str:
        """Select the best canonical name from a list of candidates.

        Args:
            names: List of candidate names.
            entity_type: Optional entity type for type-specific selection.

        Returns:
            The selected canonical name.
        """
        if not names:
            return ""

        if len(names) == 1:
            return names[0]

        normalized_results = [
            self.normalize(name, entity_type) for name in names
        ]

        scored_names = []
        for original, result in zip(names, normalized_results):
            score = self._score_canonical_candidate(result)
            scored_names.append((original, result.normalized, score))

        scored_names.sort(key=lambda x: x[2], reverse=True)

        return scored_names[0][1]

    def _score_canonical_candidate(self, result: NormalizationResult) -> float:
        """Score a canonical name candidate.

        Higher score = better candidate.
        """
        score = 0.0
        name = result.normalized

        if self._prefer_chinese:
            if result.script == NameScript.CHINESE:
                score += 10.0
            elif result.script == NameScript.MIXED:
                chinese_ratio = self._get_chinese_ratio(name)
                score += 5.0 * chinese_ratio
        else:
            if result.script == NameScript.ENGLISH:
                score += 10.0

        if result.script == NameScript.ENGLISH:
            if name[0].isupper():
                score += 2.0

        if 2 <= len(name) <= 50:
            score += 5.0
        elif len(name) > 50:
            score -= min(5.0, (len(name) - 50) * 0.1)

        if not result.changes:
            score += 3.0

        score += result.confidence * 5.0

        return score

    def _get_chinese_ratio(self, text: str) -> float:
        """Get the ratio of Chinese characters in text."""
        if not text:
            return 0.0
        chinese_count = len(re.findall(r'[\u4e00-\u9fff]', text))
        return chinese_count / len(text)

    def are_equivalent(
        self,
        name1: str,
        name2: str,
        entity_type: str | None = None,
    ) -> tuple[bool, float]:
        """Check if two names are equivalent after normalization.

        Args:
            name1: First name.
            name2: Second name.
            entity_type: Optional entity type.

        Returns:
            Tuple of (is_equivalent, confidence).
        """
        result1 = self.normalize(name1, entity_type)
        result2 = self.normalize(name2, entity_type)

        if result1.normalized == result2.normalized:
            return True, 1.0

        if result1.normalized.lower() == result2.normalized.lower():
            return True, 0.95

        if self._compare_without_suffixes(result1.normalized, result2.normalized):
            return True, 0.85

        return False, 0.0

    def _compare_without_suffixes(self, name1: str, name2: str) -> bool:
        """Compare names ignoring organization suffixes."""
        suffixes = list(self._org_suffix_map.keys()) + self._chinese_org_suffixes

        def strip_suffix(name: str) -> str:
            for suffix in suffixes:
                if name.endswith(suffix):
                    return name[:-len(suffix)].strip()
            return name

        return strip_suffix(name1) == strip_suffix(name2)

    def generate_sort_key(self, name: str) -> str:
        """Generate a sort key for the name.

        Useful for consistent ordering of entity names.
        """
        result = self.normalize(name)
        key = result.normalized.lower()

        if result.script == NameScript.CHINESE:
            key = f"z_{key}"
        elif result.script == NameScript.ENGLISH:
            key = f"a_{key}"
        else:
            key = f"m_{key}"

        return key


name_normalizer = NameNormalizer()

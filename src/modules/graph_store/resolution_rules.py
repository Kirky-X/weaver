"""Entity resolution rules for deduplication and canonical name selection.

Based on GraphRAG's entity disambiguation approach with enhancements for
Chinese language processing and domain-specific rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from core.observability.logging import get_logger

log = get_logger("entity.resolution_rules")


class MatchType(Enum):
    """Type of entity match."""

    EXACT = "exact"
    CASE_INSENSITIVE = "case_insensitive"
    ABBREVIATION = "abbreviation"
    ALIAS = "alias"
    TRANSLATION = "translation"
    FUZZY = "fuzzy"
    NONE = "none"


class EntityType(Enum):
    """Common entity types with resolution hints."""

    PERSON = "人物"
    ORGANIZATION = "组织机构"
    LOCATION = "地点"
    PRODUCT = "产品"
    EVENT = "事件"
    CONCEPT = "概念"
    UNKNOWN = "未知"


@dataclass
class ResolutionResult:
    """Result of entity resolution."""

    match_type: MatchType
    confidence: float
    canonical_name: str
    should_merge: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolutionRule:
    """A single resolution rule."""

    name: str
    entity_types: list[str] | None
    priority: int
    matcher: Callable[[str, str, str], ResolutionResult | None]
    description: str = ""


class EntityResolutionRules:
    """Collection of entity resolution rules.

    Rules are applied in priority order (lower number = higher priority).
    Each rule can either return a ResolutionResult or None to pass to next rule.
    """

    def __init__(self) -> None:
        self._rules: list[ResolutionRule] = []
        self._alias_map: dict[str, set[str]] = {}
        self._abbreviation_map: dict[str, str] = {}
        self._translation_map: dict[str, str] = {}
        self._initialize_default_rules()
        self._initialize_alias_maps()

    def _initialize_default_rules(self) -> None:
        """Initialize default resolution rules."""

        self._rules = [
            ResolutionRule(
                name="exact_match",
                entity_types=None,
                priority=0,
                matcher=self._exact_match,
                description="Exact string match",
            ),
            ResolutionRule(
                name="case_insensitive",
                entity_types=None,
                priority=10,
                matcher=self._case_insensitive_match,
                description="Case-insensitive match for English names",
            ),
            ResolutionRule(
                name="known_alias",
                entity_types=None,
                priority=20,
                matcher=self._known_alias_match,
                description="Match against known aliases",
            ),
            ResolutionRule(
                name="abbreviation",
                entity_types=None,
                priority=30,
                matcher=self._abbreviation_match,
                description="Match abbreviations to full names",
            ),
            ResolutionRule(
                name="translation",
                entity_types=None,
                priority=40,
                matcher=self._translation_match,
                description="Match Chinese-English translations",
            ),
            ResolutionRule(
                name="person_name_variant",
                entity_types=["人物"],
                priority=50,
                matcher=self._person_name_variant_match,
                description="Match person name variants (with/without title)",
            ),
            ResolutionRule(
                name="organization_variant",
                entity_types=["组织机构"],
                priority=51,
                matcher=self._organization_variant_match,
                description="Match organization name variants",
            ),
            ResolutionRule(
                name="location_variant",
                entity_types=["地点"],
                priority=52,
                matcher=self._location_variant_match,
                description="Match location name variants",
            ),
        ]

        self._rules.sort(key=lambda r: r.priority)

    def _initialize_alias_maps(self) -> None:
        """Initialize alias, abbreviation, and translation maps."""

        self._abbreviation_map = {
            "AI": "人工智能",
            "ML": "机器学习",
            "NLP": "自然语言处理",
            "CV": "计算机视觉",
            "API": "应用程序接口",
            "SDK": "软件开发工具包",
            "GDP": "国内生产总值",
            "CPI": "消费者价格指数",
            "IPO": "首次公开募股",
            "CEO": "首席执行官",
            "CTO": "首席技术官",
            "CFO": "首席财务官",
            "NBA": "美国职业篮球联赛",
            "NFL": "美国国家橄榄球联盟",
            "FIFA": "国际足球联合会",
            "WHO": "世界卫生组织",
            "UN": "联合国",
            "EU": "欧盟",
            "NATO": "北大西洋公约组织",
            "WTO": "世界贸易组织",
            "IMF": "国际货币基金组织",
            "NASA": "美国国家航空航天局",
            "FBI": "联邦调查局",
            "CIA": "中央情报局",
        }

        self._translation_map = {
            "United States": "美国",
            "United Kingdom": "英国",
            "China": "中国",
            "Japan": "日本",
            "Germany": "德国",
            "France": "法国",
            "Russia": "俄罗斯",
            "South Korea": "韩国",
            "North Korea": "朝鲜",
            "India": "印度",
            "Australia": "澳大利亚",
            "Canada": "加拿大",
            "Brazil": "巴西",
            "Italy": "意大利",
            "Spain": "西班牙",
            "Mexico": "墨西哥",
            "Taiwan": "台湾",
            "Hong Kong": "香港",
            "Macau": "澳门",
            "Beijing": "北京",
            "Shanghai": "上海",
            "Shenzhen": "深圳",
            "Guangzhou": "广州",
            "Hangzhou": "杭州",
            "Nanjing": "南京",
            "New York": "纽约",
            "Los Angeles": "洛杉矶",
            "San Francisco": "旧金山",
            "Silicon Valley": "硅谷",
            "Washington": "华盛顿",
            "London": "伦敦",
            "Paris": "巴黎",
            "Tokyo": "东京",
            "Seoul": "首尔",
            "Singapore": "新加坡",
            "Dubai": "迪拜",
        }

        self._alias_map = {
            "OpenAI": {"OpenAI Inc", "OpenAI LP", "OpenAI公司"},
            "Google": {"谷歌", "Google Inc", "Alphabet", "Google公司"},
            "Microsoft": {"微软", "Microsoft Corp", "微软公司"},
            "Apple": {"苹果", "Apple Inc", "苹果公司"},
            "Amazon": {"亚马逊", "Amazon.com", "亚马逊公司"},
            "Meta": {"Facebook", "Meta Platforms", "脸书", "Meta公司"},
            "Tesla": {"特斯拉", "Tesla Inc", "特斯拉公司"},
            "NVIDIA": {"英伟达", "Nvidia", "NVIDIA Corp", "英伟达公司"},
            "Alibaba": {"阿里巴巴", "Alibaba Group", "阿里", "阿里巴巴集团"},
            "Tencent": {"腾讯", "Tencent Holdings", "腾讯控股", "腾讯公司"},
            "ByteDance": {"字节跳动", "字节", "ByteDance Ltd"},
            "Huawei": {"华为", "Huawei Technologies", "华为技术", "华为公司"},
            "Baidu": {"百度", "Baidu Inc", "百度公司"},
            "JD": {"京东", "JD.com", "京东集团"},
            "Didi": {"滴滴", "DiDi", "滴滴出行"},
            "Pinduoduo": {"拼多多", "PDD"},
        }

    def add_rule(self, rule: ResolutionRule) -> None:
        """Add a custom resolution rule."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)

    def add_alias(self, canonical: str, alias: str) -> None:
        """Add an alias for a canonical name."""
        if canonical not in self._alias_map:
            self._alias_map[canonical] = set()
        self._alias_map[canonical].add(alias)

    def add_abbreviation(self, abbr: str, full: str) -> None:
        """Add an abbreviation mapping."""
        self._abbreviation_map[abbr] = full
        self._abbreviation_map[abbr.lower()] = full
        self._abbreviation_map[abbr.upper()] = full

    def add_translation(self, english: str, chinese: str) -> None:
        """Add a translation mapping."""
        self._translation_map[english] = chinese
        self._translation_map[chinese] = english

    def resolve(
        self,
        name: str,
        entity_type: str,
        candidates: list[dict[str, Any]] | None = None,
    ) -> ResolutionResult:
        """Resolve an entity name against candidates using rules.

        Args:
            name: The entity name to resolve.
            entity_type: The entity type.
            candidates: Optional list of candidate entities with 'canonical_name'.

        Returns:
            ResolutionResult with match information.
        """
        if candidates:
            for candidate in candidates:
                canonical = candidate.get("canonical_name", "")
                for rule in self._rules:
                    if rule.entity_types and entity_type not in rule.entity_types:
                        continue
                    result = rule.matcher(name, canonical, entity_type)
                    if result and result.match_type != MatchType.NONE:
                        return result

        return ResolutionResult(
            match_type=MatchType.NONE,
            confidence=0.0,
            canonical_name=name,
            should_merge=False,
            reason="No matching rule found",
        )

    def _exact_match(
        self,
        name: str,
        canonical: str,
        entity_type: str,
    ) -> ResolutionResult | None:
        """Check for exact match."""
        if name == canonical:
            return ResolutionResult(
                match_type=MatchType.EXACT,
                confidence=1.0,
                canonical_name=canonical,
                should_merge=True,
                reason="Exact string match",
            )
        return None

    def _case_insensitive_match(
        self,
        name: str,
        canonical: str,
        entity_type: str,
    ) -> ResolutionResult | None:
        """Check for case-insensitive match (for English names)."""
        if name.lower() == canonical.lower():
            if name != canonical:
                return ResolutionResult(
                    match_type=MatchType.CASE_INSENSITIVE,
                    confidence=0.95,
                    canonical_name=canonical,
                    should_merge=True,
                    reason="Case-insensitive match",
                    metadata={"original": name, "canonical": canonical},
                )
        return None

    def _known_alias_match(
        self,
        name: str,
        canonical: str,
        entity_type: str,
    ) -> ResolutionResult | None:
        """Check against known aliases."""
        for canonical_name, aliases in self._alias_map.items():
            if name in aliases and canonical == canonical_name:
                return ResolutionResult(
                    match_type=MatchType.ALIAS,
                    confidence=0.95,
                    canonical_name=canonical,
                    should_merge=True,
                    reason=f"Known alias of {canonical}",
                )
            if canonical in aliases and name == canonical_name:
                return ResolutionResult(
                    match_type=MatchType.ALIAS,
                    confidence=0.95,
                    canonical_name=name,
                    should_merge=True,
                    reason=f"Canonical name for alias {canonical}",
                )
            if name in aliases and canonical in aliases:
                return ResolutionResult(
                    match_type=MatchType.ALIAS,
                    confidence=0.9,
                    canonical_name=canonical_name,
                    should_merge=True,
                    reason=f"Both are aliases of {canonical_name}",
                )
        return None

    def _abbreviation_match(
        self,
        name: str,
        canonical: str,
        entity_type: str,
    ) -> ResolutionResult | None:
        """Check abbreviation mappings."""
        name_full = self._abbreviation_map.get(name)
        canonical_full = self._abbreviation_map.get(canonical)

        if name_full and name_full == canonical:
            return ResolutionResult(
                match_type=MatchType.ABBREVIATION,
                confidence=0.9,
                canonical_name=canonical,
                should_merge=True,
                reason=f"'{name}' is abbreviation of '{canonical}'",
            )
        if canonical_full and canonical_full == name:
            return ResolutionResult(
                match_type=MatchType.ABBREVIATION,
                confidence=0.9,
                canonical_name=name,
                should_merge=True,
                reason=f"'{canonical}' is abbreviation of '{name}'",
            )
        if name_full and canonical_full and name_full == canonical_full:
            return ResolutionResult(
                match_type=MatchType.ABBREVIATION,
                confidence=0.85,
                canonical_name=canonical,
                should_merge=True,
                reason=f"Both abbreviations of '{name_full}'",
            )
        return None

    def _translation_match(
        self,
        name: str,
        canonical: str,
        entity_type: str,
    ) -> ResolutionResult | None:
        """Check translation mappings."""
        name_translated = self._translation_map.get(name)
        canonical_translated = self._translation_map.get(canonical)

        if name_translated and name_translated == canonical:
            return ResolutionResult(
                match_type=MatchType.TRANSLATION,
                confidence=0.9,
                canonical_name=canonical,
                should_merge=True,
                reason=f"'{name}' is translation of '{canonical}'",
            )
        if canonical_translated and canonical_translated == name:
            return ResolutionResult(
                match_type=MatchType.TRANSLATION,
                confidence=0.9,
                canonical_name=name,
                should_merge=True,
                reason=f"'{canonical}' is translation of '{name}'",
            )
        return None

    def _person_name_variant_match(
        self,
        name: str,
        canonical: str,
        entity_type: str,
    ) -> ResolutionResult | None:
        """Match person name variants (with/without titles)."""
        titles = ["先生", "女士", "博士", "教授", "总", "董", "长", "Mr.", "Ms.", "Dr.", "Prof."]

        name_stripped = name
        canonical_stripped = canonical

        for title in titles:
            if name.endswith(title):
                name_stripped = name[:-len(title)].strip()
            if canonical.endswith(title):
                canonical_stripped = canonical[:-len(title)].strip()

        if name_stripped == canonical_stripped and name != canonical:
            return ResolutionResult(
                match_type=MatchType.ALIAS,
                confidence=0.85,
                canonical_name=canonical,
                should_merge=True,
                reason="Same person name with different title",
            )
        return None

    def _organization_variant_match(
        self,
        name: str,
        canonical: str,
        entity_type: str,
    ) -> ResolutionResult | None:
        """Match organization name variants."""
        suffixes = [
            "公司", "集团", "有限", "股份", "科技", "技术",
            "Inc.", "Corp.", "Ltd.", "LLC", "GmbH", "Co.",
            "Corporation", "Incorporated", "Limited",
        ]

        name_stripped = name
        canonical_stripped = canonical

        for suffix in suffixes:
            if name.endswith(suffix):
                name_stripped = name[:-len(suffix)].strip()
            if canonical.endswith(suffix):
                canonical_stripped = canonical[:-len(suffix)].strip()

        if name_stripped == canonical_stripped and name != canonical:
            return ResolutionResult(
                match_type=MatchType.ALIAS,
                confidence=0.85,
                canonical_name=canonical,
                should_merge=True,
                reason="Same organization with different suffix",
            )
        return None

    def _location_variant_match(
        self,
        name: str,
        canonical: str,
        entity_type: str,
    ) -> ResolutionResult | None:
        """Match location name variants."""
        suffixes = ["市", "省", "县", "区", "州", "国", "地区"]

        name_stripped = name
        canonical_stripped = canonical

        for suffix in suffixes:
            if name.endswith(suffix):
                name_stripped = name[:-len(suffix)].strip()
            if canonical.endswith(suffix):
                canonical_stripped = canonical[:-len(suffix)].strip()

        if name_stripped == canonical_stripped and name != canonical:
            return ResolutionResult(
                match_type=MatchType.ALIAS,
                confidence=0.85,
                canonical_name=canonical,
                should_merge=True,
                reason="Same location with different suffix",
            )
        return None

    def get_canonical_suggestion(
        self,
        name: str,
        entity_type: str,
    ) -> str:
        """Suggest a canonical name for a new entity.

        Args:
            name: The entity name.
            entity_type: The entity type.

        Returns:
            Suggested canonical name.
        """
        if name in self._abbreviation_map:
            return self._abbreviation_map[name]

        if name in self._translation_map:
            translated = self._translation_map[name]
            if self._is_chinese(translated):
                return translated
            if not self._is_chinese(name):
                return translated

        for canonical, aliases in self._alias_map.items():
            if name in aliases:
                return canonical

        return name

    def _is_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters."""
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    def get_all_aliases(self, canonical: str) -> set[str]:
        """Get all known aliases for a canonical name."""
        return self._alias_map.get(canonical, set())

    def get_abbreviation_full(self, abbr: str) -> str | None:
        """Get the full form of an abbreviation."""
        return self._abbreviation_map.get(abbr)

    def get_translation(self, name: str) -> str | None:
        """Get the translation of a name."""
        return self._translation_map.get(name)


resolution_rules = EntityResolutionRules()

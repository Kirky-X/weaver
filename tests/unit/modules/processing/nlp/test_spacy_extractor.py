# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for SpaCy NER extractor."""

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from modules.processing.nlp.spacy_extractor import (
    MODEL_MAP,
    SPACY_TO_ENTITY_TYPE,
    SpacyEntity,
    SpacyExtractor,
)


@dataclass
class MockSpan:
    """Mock spaCy Span for testing."""

    text: str
    label_: str
    start_char: int
    end_char: int


@dataclass
class MockDoc:
    """Mock spaCy Doc for testing."""

    text: str
    ents: list[MockSpan]


class MockNLP:
    """Mock spaCy NLP pipeline for testing."""

    def __init__(self, entities: list[MockSpan] | None = None):
        self._entities = entities or []

    def __call__(self, text: str) -> MockDoc:
        return MockDoc(text=text, ents=self._entities)

    def pipe(self, texts: list[str], **kwargs: Any) -> list[MockDoc]:
        return [MockDoc(text=t, ents=self._entities) for t in texts]


class TestSpacyEntityTypes:
    """Tests for multi-entity type extraction."""

    @pytest.fixture
    def extractor(self) -> SpacyExtractor:
        """Create a SpacyExtractor instance."""
        return SpacyExtractor()

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_person_entities_extracted(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that person names are extracted correctly."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="张三", label_="PERSON", start_char=0, end_char=2),
                MockSpan(text="李四", label_="PER", start_char=5, end_char=7),
            ]
        )
        mock_load.return_value = mock_nlp

        result = extractor.extract("张三和李四去了北京")

        assert len(result) == 2
        assert all(e.type == "人物" for e in result)
        assert result[0].name == "张三"
        assert result[1].name == "李四"

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_organization_entities_extracted(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that organization names are extracted correctly."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="阿里巴巴", label_="ORG", start_char=0, end_char=4),
                MockSpan(text="腾讯科技", label_="ORG", start_char=10, end_char=14),
            ]
        )
        mock_load.return_value = mock_nlp

        result = extractor.extract("阿里巴巴和腾讯科技发布了新产品")

        assert len(result) == 2
        assert all(e.type == "组织机构" for e in result)

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_location_entities_extracted(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that location names are extracted correctly."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="北京", label_="GPE", start_char=0, end_char=2),
                MockSpan(text="上海", label_="LOC", start_char=5, end_char=7),
            ]
        )
        mock_load.return_value = mock_nlp

        result = extractor.extract("北京和上海是中国的城市")

        assert len(result) == 2
        assert all(e.type == "地点" for e in result)

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_mixed_entity_types(self, mock_load: MagicMock, extractor: SpacyExtractor) -> None:
        """Test extraction with multiple entity types in one text."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="张三", label_="PERSON", start_char=0, end_char=2),
                MockSpan(text="阿里巴巴", label_="ORG", start_char=3, end_char=7),
                MockSpan(text="杭州", label_="GPE", start_char=8, end_char=10),
                MockSpan(text="100万", label_="CARDINAL", start_char=15, end_char=18),
            ]
        )
        mock_load.return_value = mock_nlp

        result = extractor.extract("张三在阿里巴巴杭州分公司投资了100万")

        assert len(result) == 4
        types = [e.type for e in result]
        assert "人物" in types
        assert "组织机构" in types
        assert "地点" in types
        assert "数据指标" in types


class TestLanguageDetection:
    """Tests for language detection and model selection."""

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_chinese_uses_chinese_model(self, mock_load: MagicMock) -> None:
        """Test that Chinese text uses Chinese model."""
        mock_nlp = MockNLP(entities=[])
        mock_load.return_value = mock_nlp
        extractor = SpacyExtractor()

        extractor.extract("这是一段中文文本", language="zh")

        # Should try zh models first
        assert mock_load.call_count >= 1
        first_model = mock_load.call_args_list[0][0][0]
        assert first_model.startswith("zh_core_web")

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_english_uses_english_model(self, mock_load: MagicMock) -> None:
        """Test that English text uses English model."""
        mock_nlp = MockNLP(entities=[])
        mock_load.return_value = mock_nlp
        extractor = SpacyExtractor()

        extractor.extract("This is an English text", language="en")

        first_model = mock_load.call_args_list[0][0][0]
        assert first_model.startswith("en_core_web")

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_unsupported_language_falls_back(self, mock_load: MagicMock) -> None:
        """Test that unsupported language falls back to default model."""
        mock_nlp = MockNLP(entities=[])
        mock_load.return_value = mock_nlp
        extractor = SpacyExtractor()

        extractor.extract("Texto en español", language="es")

        # Should fall back to default model
        # The logic tries model candidates for the language, then falls back
        mock_load.assert_called()

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_no_model_raises_runtime_error(self, mock_load: MagicMock) -> None:
        """Test that RuntimeError is raised when no models available."""
        mock_load.return_value = None
        extractor = SpacyExtractor()

        with pytest.raises(RuntimeError, match="No spaCy model available"):
            extractor.extract("测试文本", language="zh")


class TestEdgeCases:
    """Tests for edge cases in extraction."""

    @pytest.fixture
    def extractor(self) -> SpacyExtractor:
        """Create a SpacyExtractor instance."""
        return SpacyExtractor()

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_empty_text_returns_empty_list(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that empty text returns empty results."""
        mock_nlp = MockNLP(entities=[])
        mock_load.return_value = mock_nlp

        result = extractor.extract("", language="zh")

        assert result == []

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_whitespace_only_text(self, mock_load: MagicMock, extractor: SpacyExtractor) -> None:
        """Test that whitespace-only text returns empty results."""
        mock_nlp = MockNLP(entities=[])
        mock_load.return_value = mock_nlp

        result = extractor.extract("   \n\t  ", language="zh")

        assert result == []

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_duplicate_entities_deduplicated(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that duplicate entities are deduplicated."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="张三", label_="PERSON", start_char=0, end_char=2),
                MockSpan(text="张三", label_="PERSON", start_char=10, end_char=12),  # Duplicate
            ]
        )
        mock_load.return_value = mock_nlp

        result = extractor.extract("张三找到了张三", language="zh")

        assert len(result) == 1
        assert result[0].name == "张三"

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_unknown_entity_label_skipped(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that entities with unknown labels are skipped."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="张三", label_="PERSON", start_char=0, end_char=2),
                MockSpan(text="未知", label_="UNKNOWN_LABEL", start_char=5, end_char=7),
            ]
        )
        mock_load.return_value = mock_nlp

        result = extractor.extract("张三和未知", language="zh")

        assert len(result) == 1
        assert result[0].name == "张三"

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_special_unicode_characters(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that special Unicode characters are handled correctly."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="张三™", label_="PERSON", start_char=0, end_char=3),
            ]
        )
        mock_load.return_value = mock_nlp

        result = extractor.extract("张三™是商标", language="zh")

        assert len(result) == 1
        assert result[0].name == "张三™"
        assert result[0].start == 0
        assert result[0].end == 3


class TestBatchExtraction:
    """Tests for batch extraction functionality."""

    @pytest.fixture
    def extractor(self) -> SpacyExtractor:
        """Create a SpacyExtractor instance."""
        return SpacyExtractor(batch_size=8)

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_batch_extraction_multiple_texts(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test batch extraction of multiple texts."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="张三", label_="PERSON", start_char=0, end_char=2),
            ]
        )
        mock_load.return_value = mock_nlp

        texts = ["张三在北京", "李四在上海", "王五在广州"]
        results = extractor.extract_batch(texts, language="zh")

        assert len(results) == 3
        for result in results:
            assert len(result) == 1
            assert result[0].name == "张三"

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_batch_extraction_empty_list(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test batch extraction with empty list."""
        results = extractor.extract_batch([], language="zh")

        assert results == []

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_batch_extraction_preserves_order(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that batch extraction preserves input order."""

        # Create a mock that returns different entities for different texts
        def create_doc(text: str) -> MockDoc:
            if "北京" in text:
                return MockDoc(
                    text=text, ents=[MockSpan(text="北京", label_="GPE", start_char=0, end_char=2)]
                )
            return MockDoc(
                text=text, ents=[MockSpan(text="上海", label_="GPE", start_char=0, end_char=2)]
            )

        class OrderMockNLP:
            def pipe(self, texts: list[str], **kwargs: Any) -> list[MockDoc]:
                return [create_doc(t) for t in texts]

        mock_load.return_value = OrderMockNLP()

        texts = ["北京中心", "上海总部", "北京分部"]
        results = extractor.extract_batch(texts, language="zh")

        assert results[0][0].name == "北京"
        assert results[1][0].name == "上海"
        assert results[2][0].name == "北京"


class TestModelWarmup:
    """Tests for model warmup functionality."""

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_warmup_loads_default_languages(self, mock_load: MagicMock) -> None:
        """Test that warmup loads default languages."""
        mock_nlp = MockNLP(entities=[])
        mock_load.return_value = mock_nlp
        extractor = SpacyExtractor()

        extractor.warmup()

        # Should try to load zh and en models
        assert mock_load.call_count >= 2

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_warmup_custom_languages(self, mock_load: MagicMock) -> None:
        """Test that warmup loads specified languages."""
        mock_nlp = MockNLP(entities=[])
        mock_load.return_value = mock_nlp
        extractor = SpacyExtractor()

        extractor.warmup(languages=["en"])

        # Should only load en model
        called_models = [call[0][0] for call in mock_load.call_args_list]
        assert all(m.startswith("en_") for m in called_models)

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_warmup_handles_failure(self, mock_load: MagicMock) -> None:
        """Test that warmup handles model loading failures gracefully."""
        mock_load.return_value = None
        extractor = SpacyExtractor()

        # Should not raise exception
        extractor.warmup(languages=["zh"])


class TestSpacyEntity:
    """Tests for SpacyEntity dataclass."""

    def test_entity_creation(self) -> None:
        """Test creating a SpacyEntity."""
        entity = SpacyEntity(
            name="张三",
            type="人物",
            start=0,
            end=2,
            label="PERSON",
        )

        assert entity.name == "张三"
        assert entity.type == "人物"
        assert entity.start == 0
        assert entity.end == 2
        assert entity.label == "PERSON"

    def test_entity_equality(self) -> None:
        """Test SpacyEntity equality."""
        entity1 = SpacyEntity(name="张三", type="人物", start=0, end=2, label="PERSON")
        entity2 = SpacyEntity(name="张三", type="人物", start=0, end=2, label="PERSON")
        entity3 = SpacyEntity(name="李四", type="人物", start=0, end=2, label="PERSON")

        assert entity1 == entity2
        assert entity1 != entity3


class TestModelMap:
    """Tests for MODEL_MAP configuration."""

    def test_chinese_models_configured(self) -> None:
        """Test that Chinese models are configured."""
        assert "zh" in MODEL_MAP
        zh_models = MODEL_MAP["zh"]
        assert len(zh_models) >= 1
        assert all("zh_core_web" in m for m in zh_models)

    def test_english_models_configured(self) -> None:
        """Test that English models are configured."""
        assert "en" in MODEL_MAP
        en_models = MODEL_MAP["en"]
        assert len(en_models) >= 1
        assert all("en_core_web" in m for m in en_models)

    def test_default_model_configured(self) -> None:
        """Test that default model is configured."""
        assert "default" in MODEL_MAP
        assert len(MODEL_MAP["default"]) >= 1


class TestEntityTypeMapping:
    """Tests for SPACY_TO_ENTITY_TYPE mapping."""

    def test_person_mapping(self) -> None:
        """Test PERSON entity type mapping."""
        assert SPACY_TO_ENTITY_TYPE["PERSON"] == "人物"
        assert SPACY_TO_ENTITY_TYPE["PER"] == "人物"

    def test_organization_mapping(self) -> None:
        """Test ORG entity type mapping."""
        assert SPACY_TO_ENTITY_TYPE["ORG"] == "组织机构"

    def test_location_mapping(self) -> None:
        """Test location entity type mapping."""
        assert SPACY_TO_ENTITY_TYPE["GPE"] == "地点"
        assert SPACY_TO_ENTITY_TYPE["LOC"] == "地点"

    def test_data_metric_mapping(self) -> None:
        """Test data metric entity type mapping."""
        assert SPACY_TO_ENTITY_TYPE["CARDINAL"] == "数据指标"
        assert SPACY_TO_ENTITY_TYPE["PERCENT"] == "数据指标"
        assert SPACY_TO_ENTITY_TYPE["MONEY"] == "数据指标"

    def test_law_mapping(self) -> None:
        """Test law entity type mapping."""
        assert SPACY_TO_ENTITY_TYPE["LAW"] == "法规与政策"


class TestDisableDataMetricsFiltering:
    """Tests for disable_data_metrics filtering functionality."""

    @pytest.fixture
    def extractor(self) -> SpacyExtractor:
        """Create a SpacyExtractor instance."""
        return SpacyExtractor()

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_disable_data_metrics_filters_cardinal(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that CARDINAL entities are filtered when disable_data_metrics=True."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="张三", label_="PERSON", start_char=0, end_char=2),
                MockSpan(text="100万", label_="CARDINAL", start_char=3, end_char=6),
                MockSpan(text="阿里巴巴", label_="ORG", start_char=7, end_char=11),
            ]
        )
        mock_load.return_value = mock_nlp

        # Without filtering
        result_all = extractor.extract(
            "张三100万阿里巴巴", language="zh", disable_data_metrics=False
        )
        assert len(result_all) == 3
        types_all = [e.type for e in result_all]
        assert "数据指标" in types_all

        # With filtering
        result_filtered = extractor.extract(
            "张三100万阿里巴巴", language="zh", disable_data_metrics=True
        )
        assert len(result_filtered) == 2
        types_filtered = [e.type for e in result_filtered]
        assert "数据指标" not in types_filtered

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_disable_data_metrics_filters_percent(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that PERCENT entities are filtered when disable_data_metrics=True."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="12.5%", label_="PERCENT", start_char=0, end_char=4),
                MockSpan(text="腾讯", label_="ORG", start_char=5, end_char=7),
            ]
        )
        mock_load.return_value = mock_nlp

        result = extractor.extract("12.5%腾讯", language="zh", disable_data_metrics=True)

        assert len(result) == 1
        assert result[0].type == "组织机构"

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_disable_data_metrics_filters_money(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that MONEY entities are filtered when disable_data_metrics=True."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="100万元", label_="MONEY", start_char=0, end_char=4),
            ]
        )
        mock_load.return_value = mock_nlp

        result = extractor.extract("100万元投资", language="zh", disable_data_metrics=True)

        assert len(result) == 0

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_disable_data_metrics_default_false(
        self, mock_load: MagicMock, extractor: SpacyExtractor
    ) -> None:
        """Test that disable_data_metrics defaults to False (no filtering)."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="100", label_="CARDINAL", start_char=0, end_char=3),
            ]
        )
        mock_load.return_value = mock_nlp

        # Default behavior should include data metrics
        result = extractor.extract("100", language="zh")
        assert len(result) == 1
        assert result[0].type == "数据指标"

    @patch("modules.processing.nlp.spacy_extractor.SpacyExtractor._load")
    def test_batch_extraction_disable_data_metrics(self, mock_load: MagicMock) -> None:
        """Test that disable_data_metrics works with batch extraction."""
        mock_nlp = MockNLP(
            entities=[
                MockSpan(text="100万", label_="CARDINAL", start_char=0, end_char=3),
                MockSpan(text="腾讯", label_="ORG", start_char=4, end_char=6),
            ]
        )
        mock_load.return_value = mock_nlp
        extractor = SpacyExtractor(batch_size=8)

        texts = ["100万腾讯", "200万阿里"]
        results = extractor.extract_batch(texts, language="zh", disable_data_metrics=True)

        assert len(results) == 2
        for result in results:
            # Each should only have the ORG entity, CARDINAL filtered
            assert len(result) == 1
            assert result[0].type == "组织机构"

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SpacyExtractor module."""

from unittest.mock import MagicMock, patch

import pytest

from modules.processing.nlp.spacy_extractor import (
    MODEL_MAP,
    SPACY_TO_ENTITY_TYPE,
    SpacyEntity,
    SpacyExtractor,
)


class TestSpacyExtractor:
    """Tests for SpacyExtractor."""

    @pytest.fixture
    def extractor(self):
        """Create spacy extractor instance."""
        return SpacyExtractor()

    def test_initialization(self, extractor):
        """Test extractor initializes correctly."""
        assert extractor._models == {}

    def test_model_map_defined(self):
        """Test model map is defined."""
        assert "zh" in MODEL_MAP
        assert "en" in MODEL_MAP
        assert "default" in MODEL_MAP
        assert isinstance(MODEL_MAP["zh"], list)
        assert "zh_core_web_trf" in MODEL_MAP["zh"]
        assert "en_core_web_trf" in MODEL_MAP["en"]

    def test_spacy_to_entity_type_mapping(self):
        """Test spaCy to entity type mapping."""
        assert SPACY_TO_ENTITY_TYPE["PER"] == "人物"
        assert SPACY_TO_ENTITY_TYPE["PERSON"] == "人物"
        assert SPACY_TO_ENTITY_TYPE["ORG"] == "组织机构"
        assert SPACY_TO_ENTITY_TYPE["GPE"] == "地点"
        assert SPACY_TO_ENTITY_TYPE["LOC"] == "地点"
        assert SPACY_TO_ENTITY_TYPE["TIME"] == "事件"
        assert SPACY_TO_ENTITY_TYPE["DATE"] == "事件"
        assert SPACY_TO_ENTITY_TYPE["EVENT"] == "事件"
        assert SPACY_TO_ENTITY_TYPE["CARDINAL"] == "数据指标"
        assert SPACY_TO_ENTITY_TYPE["PERCENT"] == "数据指标"
        assert SPACY_TO_ENTITY_TYPE["MONEY"] == "数据指标"
        assert SPACY_TO_ENTITY_TYPE["LAW"] == "法规与政策"

    def test_extract_chinese(self, extractor):
        """Test Chinese entity extraction."""
        with patch.object(extractor, "_get_nlp") as mock_get_nlp:
            mock_doc = MagicMock()
            mock_ent = MagicMock()
            mock_ent.text = "张三"
            mock_ent.label_ = "PER"
            mock_ent.start_char = 0
            mock_ent.end_char = 2
            mock_doc.ents = [mock_ent]
            mock_nlp = MagicMock(return_value=mock_doc)
            mock_get_nlp.return_value = mock_nlp

            result = extractor.extract("张三去了北京", language="zh")

            assert len(result) == 1
            assert result[0].name == "张三"
            assert result[0].type == "人物"

    def test_extract_english(self, extractor):
        """Test English entity extraction."""
        with patch.object(extractor, "_get_nlp") as mock_get_nlp:
            mock_doc = MagicMock()
            mock_ent = MagicMock()
            mock_ent.text = "John Smith"
            mock_ent.label_ = "PERSON"
            mock_ent.start_char = 0
            mock_ent.end_char = 10
            mock_doc.ents = [mock_ent]
            mock_nlp = MagicMock(return_value=mock_doc)
            mock_get_nlp.return_value = mock_nlp

            result = extractor.extract("John Smith went to New York", language="en")

            assert len(result) == 1
            assert result[0].name == "John Smith"
            assert result[0].type == "人物"

    def test_extract_default_model(self, extractor):
        """Test default model selection."""
        with patch.object(extractor, "_get_nlp") as mock_get_nlp:
            mock_doc = MagicMock()
            mock_doc.ents = []
            mock_nlp = MagicMock(return_value=mock_doc)
            mock_get_nlp.return_value = mock_nlp

            extractor.extract("Some text", language="unknown")

            mock_get_nlp.assert_called_with("unknown")

    def test_entity_type_mapping(self, extractor):
        """Test entity type mapping for all types."""
        with patch.object(extractor, "_get_nlp") as mock_get_nlp:
            mock_doc = MagicMock()
            entities = []
            for label in ["PER", "ORG", "GPE", "TIME", "MONEY", "LAW"]:
                ent = MagicMock()
                ent.text = f"entity_{label}"
                ent.label_ = label
                ent.start_char = 0
                ent.end_char = 10
                entities.append(ent)
            mock_doc.ents = entities
            mock_nlp = MagicMock(return_value=mock_doc)
            mock_get_nlp.return_value = mock_nlp

            result = extractor.extract("test", language="zh")

            assert len(result) == len(entities)

    def test_deduplication(self, extractor):
        """Test entity deduplication."""
        with patch.object(extractor, "_get_nlp") as mock_get_nlp:
            mock_doc = MagicMock()
            mock_ent1 = MagicMock()
            mock_ent1.text = "张三"
            mock_ent1.label_ = "PER"
            mock_ent1.start_char = 0
            mock_ent1.end_char = 2
            mock_ent2 = MagicMock()
            mock_ent2.text = "张三"
            mock_ent2.label_ = "PER"
            mock_ent2.start_char = 10
            mock_ent2.end_char = 12
            mock_doc.ents = [mock_ent1, mock_ent2]
            mock_nlp = MagicMock(return_value=mock_doc)
            mock_get_nlp.return_value = mock_nlp

            result = extractor.extract("张三和张三", language="zh")

            assert len(result) == 1

    def test_model_caching(self, extractor):
        """Test model caching via instance-level cache."""
        assert hasattr(extractor, "_models")
        assert extractor._models == {}

    def test_empty_text(self, extractor):
        """Test empty text handling."""
        with patch.object(extractor, "_get_nlp") as mock_get_nlp:
            mock_doc = MagicMock()
            mock_doc.ents = []
            mock_nlp = MagicMock(return_value=mock_doc)
            mock_get_nlp.return_value = mock_nlp

            result = extractor.extract("", language="zh")

            assert result == []

    def test_unknown_label_ignored(self, extractor):
        """Test unknown labels are ignored."""
        with patch.object(extractor, "_get_nlp") as mock_get_nlp:
            mock_doc = MagicMock()
            mock_ent = MagicMock()
            mock_ent.text = "Unknown"
            mock_ent.label_ = "UNKNOWN_LABEL"
            mock_ent.start_char = 0
            mock_ent.end_char = 7
            mock_doc.ents = [mock_ent]
            mock_nlp = MagicMock(return_value=mock_doc)
            mock_get_nlp.return_value = mock_nlp

            result = extractor.extract("Unknown", language="zh")

            assert len(result) == 0


class TestSpacyEntity:
    """Tests for SpacyEntity dataclass."""

    def test_entity_creation(self):
        """Test entity creation."""
        entity = SpacyEntity(name="张三", type="人物", start=0, end=2, label="PER")
        assert entity.name == "张三"
        assert entity.type == "人物"
        assert entity.start == 0
        assert entity.end == 2
        assert entity.label == "PER"

    def test_entity_attributes(self):
        """Test entity attributes are accessible."""
        entity = SpacyEntity(name="Apple Inc", type="组织机构", start=10, end=20, label="ORG")
        assert hasattr(entity, "name")
        assert hasattr(entity, "type")
        assert hasattr(entity, "start")
        assert hasattr(entity, "end")
        assert hasattr(entity, "label")

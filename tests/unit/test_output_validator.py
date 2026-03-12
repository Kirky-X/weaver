"""Unit tests for output validator."""

import pytest

from core.llm.output_validator import (
    parse_llm_json,
    OutputParserException,
    ClassifierOutput,
    AnalyzeOutput,
    CredibilityOutput,
    EntityExtractorOutput,
)


class TestParseLlmJson:
    """Tests for parse_llm_json function."""

    def test_parse_valid_json(self):
        """Test parsing valid JSON string."""
        raw = '{"is_news": true, "confidence": 0.95}'
        result = parse_llm_json(raw, ClassifierOutput)
        assert result.is_news is True
        assert result.confidence == 0.95

    def test_parse_json_with_markdown_block(self):
        """Test parsing JSON wrapped in markdown code block."""
        raw = '```json\n{"is_news": false, "confidence": 0.8}\n```'
        result = parse_llm_json(raw, ClassifierOutput)
        assert result.is_news is False
        assert result.confidence == 0.8

    def test_parse_json_with_plain_code_block(self):
        """Test parsing JSON wrapped in plain code block."""
        raw = '```\n{"is_news": true, "confidence": 0.9}\n```'
        result = parse_llm_json(raw, ClassifierOutput)
        assert result.is_news is True

    def test_parse_invalid_json_raises(self):
        """Test invalid JSON raises OutputParserException."""
        raw = 'not valid json'
        with pytest.raises(OutputParserException):
            parse_llm_json(raw, ClassifierOutput)

    def test_parse_missing_required_field_raises(self):
        """Test missing required field raises exception."""
        raw = '{"confidence": 0.5}'
        with pytest.raises(OutputParserException):
            parse_llm_json(raw, ClassifierOutput)

    def test_parse_with_extra_whitespace(self):
        """Test parsing with extra whitespace."""
        raw = '  \n  {"is_news": true, "confidence": 0.95}  \n  '
        result = parse_llm_json(raw, ClassifierOutput)
        assert result.is_news is True


class TestClassifierOutput:
    """Tests for ClassifierOutput model."""

    def test_valid_output(self):
        """Test valid ClassifierOutput."""
        output = ClassifierOutput(is_news=True, confidence=0.9)
        assert output.is_news is True
        assert output.confidence == 0.9

    def test_confidence_range_valid(self):
        """Test confidence within valid range."""
        output = ClassifierOutput(is_news=False, confidence=0.5)
        assert 0 <= output.confidence <= 1

    def test_confidence_boundary_zero(self):
        """Test confidence at zero boundary."""
        output = ClassifierOutput(is_news=True, confidence=0.0)
        assert output.confidence == 0.0

    def test_confidence_boundary_one(self):
        """Test confidence at one boundary."""
        output = ClassifierOutput(is_news=True, confidence=1.0)
        assert output.confidence == 1.0


class TestAnalyzeOutput:
    """Tests for AnalyzeOutput model."""

    def test_valid_output(self):
        """Test valid AnalyzeOutput."""
        output = AnalyzeOutput(
            summary="Test summary",
            event_time="2024-01-01T00:00:00",
            subjects=["subject1", "subject2"],
            key_data=["data1"],
            impact="Test impact",
            has_data=True,
            sentiment="positive",
            sentiment_score=0.8,
            primary_emotion="乐观",
            emotion_targets=["target1"],
            score=0.75,
        )
        assert output.summary == "Test summary"
        assert output.sentiment == "positive"

    def test_optional_event_time_none(self):
        """Test event_time can be None."""
        output = AnalyzeOutput(
            summary="Summary",
            event_time=None,
            subjects=[],
            key_data=[],
            impact="Impact",
            has_data=False,
            sentiment="neutral",
            sentiment_score=0.5,
            primary_emotion="平静",
            emotion_targets=[],
            score=0.5,
        )
        assert output.event_time is None

    def test_score_range_validation(self):
        """Test score must be in valid range."""
        output = AnalyzeOutput(
            summary="Summary",
            event_time=None,
            subjects=[],
            key_data=[],
            impact="Impact",
            has_data=False,
            sentiment="neutral",
            sentiment_score=0.5,
            primary_emotion="平静",
            emotion_targets=[],
            score=0.0,
        )
        assert output.score == 0.0


class TestCredibilityOutput:
    """Tests for CredibilityOutput model."""

    def test_valid_output(self):
        """Test valid CredibilityOutput."""
        output = CredibilityOutput(score=0.85, flags=["verified"])
        assert output.score == 0.85
        assert output.flags == ["verified"]

    def test_empty_flags(self):
        """Test empty flags list."""
        output = CredibilityOutput(score=0.5, flags=[])
        assert output.flags == []

    def test_default_flags(self):
        """Test default flags is empty list."""
        output = CredibilityOutput(score=0.7)
        assert output.flags == []

    def test_multiple_flags(self):
        """Test multiple flags."""
        output = CredibilityOutput(
            score=0.3,
            flags=["low_source_authority", "no_cross_verification", "outdated"],
        )
        assert len(output.flags) == 3


class TestEntityExtractorOutput:
    """Tests for EntityExtractorOutput model."""

    def test_valid_output(self):
        """Test valid EntityExtractorOutput."""
        output = EntityExtractorOutput(
            entities=[
                {"name": "张三", "type": "人物", "description": "测试人物"}
            ],
            relations=[
                {"source": "张三", "target": "公司A", "type": "任职"}
            ],
        )
        assert len(output.entities) == 1
        assert len(output.relations) == 1

    def test_empty_entities_and_relations(self):
        """Test empty entities and relations."""
        output = EntityExtractorOutput(entities=[], relations=[])
        assert output.entities == []
        assert output.relations == []

    def test_multiple_entities(self):
        """Test multiple entities."""
        output = EntityExtractorOutput(
            entities=[
                {"name": "实体1", "type": "人物"},
                {"name": "实体2", "type": "组织机构"},
                {"name": "实体3", "type": "地点"},
            ],
            relations=[],
        )
        assert len(output.entities) == 3

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for temporal parser module."""

from datetime import datetime, timedelta

import pytest

from modules.knowledge.search.temporal.parser import TemporalParser
from modules.knowledge.search.temporal.schemas import TimeAnchor, TimeWindow


@pytest.mark.unit
def test_chinese_yesterday():
    """Test parsing '昨天' expression."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 2)
    anchors = parser.parse("昨天", ref)
    assert len(anchors) == 1
    assert anchors[0].resolved == datetime(2026, 4, 1)
    assert anchors[0].expression == "昨天"


@pytest.mark.unit
def test_chinese_today():
    """Test parsing '今天' expression."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 2, 15, 30)
    anchors = parser.parse("今天", ref)
    assert len(anchors) == 1
    assert anchors[0].resolved == ref.date()


@pytest.mark.unit
def test_chinese_last_week():
    """Test parsing '上周' expression."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 2)
    anchors = parser.parse("上周", ref)
    assert len(anchors) == 1
    expected = ref - timedelta(weeks=1)
    assert anchors[0].resolved == expected


@pytest.mark.unit
def test_days_ago():
    """Test parsing '3天前' expression."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 5)
    anchors = parser.parse("3天前", ref)
    assert len(anchors) == 1
    assert anchors[0].resolved == datetime(2026, 4, 2)


@pytest.mark.unit
def test_months_ago():
    """Test parsing '2个月前' expression."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 2)
    anchors = parser.parse("2个月前", ref)
    assert len(anchors) == 1
    # 2 months ≈ 60 days
    expected = ref - timedelta(days=60)
    assert anchors[0].resolved == expected


@pytest.mark.unit
def test_next_week():
    """Test parsing '下周' expression."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 2)
    anchors = parser.parse("下周", ref)
    assert len(anchors) == 1
    expected = ref + timedelta(weeks=1)
    assert anchors[0].resolved == expected


@pytest.mark.unit
def test_this_month():
    """Test parsing '本月' expression."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 15)
    anchors = parser.parse("本月", ref)
    assert len(anchors) == 1
    assert anchors[0].resolved == datetime(2026, 4, 1)


@pytest.mark.unit
def test_last_month():
    """Test parsing '上月' expression."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 15)
    anchors = parser.parse("上月", ref)
    assert len(anchors) == 1
    expected = ref.replace(day=1) - timedelta(days=1)
    assert anchors[0].resolved == expected


@pytest.mark.unit
def test_no_temporal_expression():
    """Test parsing with no temporal expressions."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 2)
    anchors = parser.parse("普通查询没有时间表达式", ref)
    assert len(anchors) == 0


@pytest.mark.unit
def test_time_window_with_anchors():
    """Test time window resolution with anchors."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 2)
    anchors = parser.parse("上周", ref)
    window = parser.resolve_time_window(anchors)

    assert window.relative_to_query is True
    assert window.start is not None
    assert window.end is not None


@pytest.mark.unit
def test_time_window_no_anchors():
    """Test time window with no anchors returns empty window."""
    parser = TemporalParser()
    window = parser.resolve_time_window([])
    assert window.relative_to_query is False
    assert window.start is None
    assert window.end is None


@pytest.mark.unit
def test_extract_patterns():
    """Test extracting temporal pattern hints from text."""
    parser = TemporalParser()
    patterns = parser.extract_patterns_from_text("上周五发生了什么")
    assert len(patterns) > 0


@pytest.mark.unit
def test_english_yesterday():
    """Test parsing English 'yesterday' expression."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 2)
    anchors = parser.parse("yesterday", ref)
    assert len(anchors) == 1
    assert anchors[0].resolved == datetime(2026, 4, 1)


@pytest.mark.unit
def test_english_last_week():
    """Test parsing English 'last week' expression."""
    parser = TemporalParser()
    ref = datetime(2026, 4, 2)
    anchors = parser.parse("last week", ref)
    assert len(anchors) == 1
    expected = ref - timedelta(weeks=1)
    assert anchors[0].resolved == expected

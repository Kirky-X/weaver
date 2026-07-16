# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for CleanerOutput._repair_llm_output model_validator.

Covers Bug-C: CleanerOutput validation rejected valid-LLM-but-wrong-type inputs
because the prompt explicitly tells the LLM to fill missing fields with null,
but CleanerContent.title/body were typed as `str` (non-Optional). The
_repair_llm_output validator bridges this prompt-model contract gap and
also defends against other common LLM type drift (int/list/dict for str fields,
None for list fields, non-dict content, etc.).

Bug-C HIGH-1 fix: CleanerContent.title/body changed to `str | None = None`
to align with prompt contract; caller applies `or ""` fallback.

Bug-C HIGH-2 fix: _coerce_str_field helper never str()s dict/list — extracts
subfield or returns None, preventing silent data corruption from garbage
repr strings like "{'text': '...'}".
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.llm.validation.output_validator import CleanerOutput


class TestRepairContentField:
    """Repair content field type anomalies."""

    def test_content_title_none_preserved(self) -> None:
        """LLM returns content.title=null per prompt; None is valid (str | None)."""
        r = CleanerOutput.model_validate({"content": {"title": None, "body": "b"}})
        assert r.content.title is None
        assert r.content.body == "b"

    def test_content_body_none_preserved(self) -> None:
        """LLM returns content.body=null per prompt; None is valid (str | None)."""
        r = CleanerOutput.model_validate({"content": {"title": "t", "body": None}})
        assert r.content.title == "t"
        assert r.content.body is None

    def test_content_subtitle_none_kept_as_none(self) -> None:
        """subtitle is str|None; None is valid and must be preserved."""
        r = CleanerOutput.model_validate({"content": {"title": "t", "body": "b", "subtitle": None}})
        assert r.content.subtitle is None

    def test_content_summary_none_kept_as_none(self) -> None:
        """summary is str|None; None is valid and must be preserved."""
        r = CleanerOutput.model_validate({"content": {"title": "t", "body": "b", "summary": None}})
        assert r.content.summary is None

    def test_content_none_rebuilds_from_top_level_fields(self) -> None:
        """content=null triggers rebuild from top-level title/body fields."""
        r = CleanerOutput.model_validate({"title": "T", "body": "B"})
        assert r.content.title == "T"
        assert r.content.body == "B"

    def test_content_str_resets_to_default_content(self) -> None:
        """content=str (LLM wrongly returns a string) resets to defaults (None)."""
        r = CleanerOutput.model_validate({"content": "some string"})
        assert r.content.title is None
        assert r.content.body is None

    def test_content_list_resets_to_default_content(self) -> None:
        """content=list resets to defaults (None)."""
        r = CleanerOutput.model_validate({"content": ["a", "b"]})
        assert r.content.title is None
        assert r.content.body is None

    def test_content_int_resets_to_default_content(self) -> None:
        """content=int resets to defaults (None)."""
        r = CleanerOutput.model_validate({"content": 123})
        assert r.content.title is None
        assert r.content.body is None

    def test_content_title_non_str_coerced_to_str(self) -> None:
        """content.title=int (LLM returns numeric title) coerced to str."""
        r = CleanerOutput.model_validate({"content": {"title": 12345, "body": "b"}})
        assert r.content.title == "12345"

    def test_content_body_non_str_coerced_to_str(self) -> None:
        """content.body=int coerced to str."""
        r = CleanerOutput.model_validate({"content": {"title": "t", "body": 67890}})
        assert r.content.body == "67890"

    # --- Bug-C HIGH-2: dict/list must not be str()ed ---

    def test_content_title_dict_extracts_text_field(self) -> None:
        """LLM returns title as dict with 'text' subfield; extract it."""
        r = CleanerOutput.model_validate(
            {"content": {"title": {"text": "Real Title"}, "body": "b"}}
        )
        assert r.content.title == "Real Title"

    def test_content_body_dict_extracts_value_field(self) -> None:
        """LLM returns body as dict with 'value' subfield; extract it."""
        r = CleanerOutput.model_validate(
            {"content": {"title": "t", "body": {"value": "Real Body"}}}
        )
        assert r.content.body == "Real Body"

    def test_content_title_dict_no_known_subfield_becomes_none(self) -> None:
        """LLM returns title as dict without recognizable subfield; None (not str(dict))."""
        r = CleanerOutput.model_validate({"content": {"title": {"foo": "bar"}, "body": "b"}})
        assert r.content.title is None

    def test_content_body_list_takes_first_str(self) -> None:
        """LLM returns body as list; take first str element."""
        r = CleanerOutput.model_validate({"content": {"title": "t", "body": ["first", "second"]}})
        assert r.content.body == "first"

    def test_content_title_bool_becomes_none(self) -> None:
        """LLM returns title=true; bool must not become 'True' string."""
        r = CleanerOutput.model_validate({"content": {"title": True, "body": "b"}})
        assert r.content.title is None

    def test_content_subtitle_dict_extracts_text_field(self) -> None:
        """subtitle as dict also gets subfield extraction."""
        r = CleanerOutput.model_validate(
            {"content": {"title": "t", "body": "b", "subtitle": {"text": "Sub"}}}
        )
        assert r.content.subtitle == "Sub"


class TestRepairPublishTimeField:
    """Repair publish_time field type anomalies (str|None)."""

    def test_publish_time_none_kept_as_none(self) -> None:
        r = CleanerOutput.model_validate(
            {"publish_time": None, "content": {"title": "t", "body": "b"}}
        )
        assert r.publish_time is None

    def test_publish_time_str_preserved(self) -> None:
        r = CleanerOutput.model_validate(
            {"publish_time": "2024-01-01 10:00:00", "content": {"title": "t", "body": "b"}}
        )
        assert r.publish_time == "2024-01-01 10:00:00"

    def test_publish_time_int_coerced_to_str(self) -> None:
        """LLM returns Unix timestamp as int; coerce to str."""
        r = CleanerOutput.model_validate(
            {"publish_time": 1234567890, "content": {"title": "t", "body": "b"}}
        )
        assert r.publish_time == "1234567890"

    def test_publish_time_list_takes_first_element(self) -> None:
        """LLM returns list; take first element as str."""
        r = CleanerOutput.model_validate(
            {"publish_time": ["2024-01-01"], "content": {"title": "t", "body": "b"}}
        )
        assert r.publish_time == "2024-01-01"

    def test_publish_time_empty_list_becomes_none(self) -> None:
        r = CleanerOutput.model_validate(
            {"publish_time": [], "content": {"title": "t", "body": "b"}}
        )
        assert r.publish_time is None

    def test_publish_time_dict_extracts_date_field(self) -> None:
        """LLM returns {'date': '2024-01-01'}; extract date value."""
        r = CleanerOutput.model_validate(
            {"publish_time": {"date": "2024-01-01"}, "content": {"title": "t", "body": "b"}}
        )
        assert r.publish_time == "2024-01-01"

    def test_publish_time_dict_extracts_value_field_when_no_date(self) -> None:
        r = CleanerOutput.model_validate(
            {"publish_time": {"value": "2024-01-01"}, "content": {"title": "t", "body": "b"}}
        )
        assert r.publish_time == "2024-01-01"

    def test_publish_time_dict_no_known_subfield_becomes_none(self) -> None:
        """Dict without recognizable fields becomes None (not str(dict) garbage)."""
        r = CleanerOutput.model_validate(
            {"publish_time": {"unknown": "x"}, "content": {"title": "t", "body": "b"}}
        )
        assert r.publish_time is None

    def test_publish_time_bool_becomes_none(self) -> None:
        """bool must not become 'True' string (bool is int subclass)."""
        r = CleanerOutput.model_validate(
            {"publish_time": True, "content": {"title": "t", "body": "b"}}
        )
        assert r.publish_time is None

    def test_publish_time_dict_with_none_subfield_becomes_none(self) -> None:
        """{'date': None} has no extractable value; becomes None."""
        r = CleanerOutput.model_validate(
            {"publish_time": {"date": None}, "content": {"title": "t", "body": "b"}}
        )
        assert r.publish_time is None


class TestRepairAuthorField:
    """Repair author field type anomalies (str|None)."""

    def test_author_none_kept_as_none(self) -> None:
        r = CleanerOutput.model_validate({"author": None, "content": {"title": "t", "body": "b"}})
        assert r.author is None

    def test_author_str_preserved(self) -> None:
        r = CleanerOutput.model_validate({"author": "张三", "content": {"title": "t", "body": "b"}})
        assert r.author == "张三"

    def test_author_int_coerced_to_str(self) -> None:
        r = CleanerOutput.model_validate({"author": 42, "content": {"title": "t", "body": "b"}})
        assert r.author == "42"

    def test_author_dict_extracts_name_field(self) -> None:
        """LLM returns {'name': '张三'}; extract name value."""
        r = CleanerOutput.model_validate(
            {"author": {"name": "张三"}, "content": {"title": "t", "body": "b"}}
        )
        assert r.author == "张三"

    def test_author_list_takes_first_element(self) -> None:
        r = CleanerOutput.model_validate(
            {"author": ["李四"], "content": {"title": "t", "body": "b"}}
        )
        assert r.author == "李四"

    def test_author_empty_list_becomes_none(self) -> None:
        r = CleanerOutput.model_validate({"author": [], "content": {"title": "t", "body": "b"}})
        assert r.author is None

    def test_author_bool_becomes_none(self) -> None:
        """bool must not become 'True' string."""
        r = CleanerOutput.model_validate({"author": True, "content": {"title": "t", "body": "b"}})
        assert r.author is None

    def test_author_dict_no_known_subfield_becomes_none(self) -> None:
        """Dict without name/value/text becomes None (not str(dict) garbage)."""
        r = CleanerOutput.model_validate(
            {"author": {"foo": "bar"}, "content": {"title": "t", "body": "b"}}
        )
        assert r.author is None


class TestRepairTagsField:
    """Repair tags field type anomalies (list[str])."""

    def test_tags_none_becomes_empty_list(self) -> None:
        r = CleanerOutput.model_validate({"tags": None, "content": {"title": "t", "body": "b"}})
        assert r.tags == []

    def test_tags_int_becomes_empty_list(self) -> None:
        r = CleanerOutput.model_validate({"tags": 123, "content": {"title": "t", "body": "b"}})
        assert r.tags == []

    def test_tags_str_becomes_empty_list(self) -> None:
        """A bare string is not a list of strings; reset to empty."""
        r = CleanerOutput.model_validate(
            {"tags": "not a list", "content": {"title": "t", "body": "b"}}
        )
        assert r.tags == []

    def test_tags_with_none_items_filtered(self) -> None:
        r = CleanerOutput.model_validate(
            {"tags": [None, "a", None, "b"], "content": {"title": "t", "body": "b"}}
        )
        assert r.tags == ["a", "b"]

    def test_tags_with_numeric_items_coerced(self) -> None:
        """int/float items are coerced to str (numbers as tags are valid)."""
        r = CleanerOutput.model_validate(
            {"tags": [1, "a", 2.5], "content": {"title": "t", "body": "b"}}
        )
        assert r.tags == ["1", "a", "2.5"]

    def test_tags_empty_list_preserved(self) -> None:
        r = CleanerOutput.model_validate({"tags": [], "content": {"title": "t", "body": "b"}})
        assert r.tags == []

    # --- Bug-C HIGH-2: dict/list/bool items must not be str()ed ---

    def test_tags_dict_item_filtered(self) -> None:
        """dict item must be filtered out, not str()ed to \"{'name': 'x'}\"."""
        r = CleanerOutput.model_validate(
            {"tags": [{"name": "x"}], "content": {"title": "t", "body": "b"}}
        )
        assert r.tags == []

    def test_tags_list_item_filtered(self) -> None:
        """nested list item must be filtered out, not str()ed to '[]'."""
        r = CleanerOutput.model_validate(
            {"tags": [["a", "b"]], "content": {"title": "t", "body": "b"}}
        )
        assert r.tags == []

    def test_tags_bool_item_filtered(self) -> None:
        """bool item must be filtered out, not str()ed to 'True'."""
        r = CleanerOutput.model_validate(
            {"tags": [True, False], "content": {"title": "t", "body": "b"}}
        )
        assert r.tags == []

    def test_tags_mixed_valid_and_invalid(self) -> None:
        """Mix of str, int, dict, list, None, bool — only str and int/float kept."""
        r = CleanerOutput.model_validate(
            {
                "tags": ["valid", 42, None, {"bad": "x"}, ["nested"], True, 3.14],
                "content": {"title": "t", "body": "b"},
            }
        )
        assert r.tags == ["valid", "42", "3.14"]


class TestRepairEntitiesField:
    """Repair entities field type anomalies (list[CleanerEntity])."""

    def test_entities_none_becomes_empty_list(self) -> None:
        r = CleanerOutput.model_validate({"entities": None, "content": {"title": "t", "body": "b"}})
        assert r.entities == []

    def test_entities_int_becomes_empty_list(self) -> None:
        r = CleanerOutput.model_validate({"entities": 123, "content": {"title": "t", "body": "b"}})
        assert r.entities == []

    def test_entities_with_none_items_filtered(self) -> None:
        r = CleanerOutput.model_validate(
            {"entities": [None], "content": {"title": "t", "body": "b"}}
        )
        assert r.entities == []

    def test_entities_with_dict_missing_name_filtered(self) -> None:
        """Entities must have both name and type to be retained."""
        r = CleanerOutput.model_validate(
            {"entities": [{"foo": "bar"}], "content": {"title": "t", "body": "b"}}
        )
        assert r.entities == []

    def test_entities_with_name_none_filtered(self) -> None:
        r = CleanerOutput.model_validate(
            {"entities": [{"name": None, "type": "x"}], "content": {"title": "t", "body": "b"}}
        )
        assert r.entities == []

    def test_entities_valid_dict_retained(self) -> None:
        r = CleanerOutput.model_validate(
            {
                "entities": [{"name": "EntityA", "type": "组织机构", "description": "desc"}],
                "content": {"title": "t", "body": "b"},
            }
        )
        assert len(r.entities) == 1
        assert r.entities[0].name == "EntityA"

    def test_entities_mixed_valid_and_invalid(self) -> None:
        r = CleanerOutput.model_validate(
            {
                "entities": [
                    None,
                    {"foo": "bar"},
                    {"name": "Valid", "type": "人物", "description": "ok"},
                    {"name": None, "type": "x"},
                ],
                "content": {"title": "t", "body": "b"},
            }
        )
        assert len(r.entities) == 1
        assert r.entities[0].name == "Valid"


class TestRepairNonDictInput:
    """Repair when the entire LLM output is not a dict."""

    def test_non_dict_input_returns_unchanged(self) -> None:
        """model_validator(mode='before') returns non-dict as-is; Pydantic then raises."""
        with pytest.raises(ValidationError):
            CleanerOutput.model_validate("not a dict")

    def test_empty_dict_uses_defaults(self) -> None:
        r = CleanerOutput.model_validate({})
        assert r.publish_time is None
        assert r.author is None
        assert r.content.title is None
        assert r.content.body is None
        assert r.tags == []
        assert r.entities == []


class TestRepairComplexScenarios:
    """Complex scenarios combining multiple anomalies — mirrors production failure."""

    def test_production_failure_pattern(self) -> None:
        """Reproduces the exact production failure: content.title=None, content.body=None.

        This is the case that caused `provider_call_failed` for 36kr article
        https://www.36kr.com/p/2605890540329352 on 2026-07-17 05:26:44.
        """
        llm_output = {
            "publish_time": None,
            "author": None,
            "content": {"title": None, "subtitle": None, "summary": None, "body": None},
            "tags": [],
            "entities": [],
        }
        r = CleanerOutput.model_validate(llm_output)
        assert r.content.title is None
        assert r.content.body is None
        assert r.content.subtitle is None
        assert r.content.summary is None

    def test_all_fields_wrong_type(self) -> None:
        """Stress test: every field is the wrong type; validator must repair all."""
        llm_output = {
            "publish_time": 1234567890,
            "author": {"name": "Author"},
            "content": "not a dict",
            "tags": None,
            "entities": None,
        }
        r = CleanerOutput.model_validate(llm_output)
        assert r.publish_time == "1234567890"
        assert r.author == "Author"
        assert r.content.title is None
        assert r.content.body is None
        assert r.tags == []
        assert r.entities == []

    def test_top_level_title_body_with_null_content(self) -> None:
        """LLM returns content=null but top-level title/body present."""
        llm_output = {
            "publish_time": None,
            "content": None,
            "title": "Top Title",
            "body": "Top Body",
        }
        r = CleanerOutput.model_validate(llm_output)
        assert r.content.title == "Top Title"
        assert r.content.body == "Top Body"

    # --- Bug-C HIGH-2: 蓝军挑战 — dict/list must not produce garbage strings ---

    def test_content_body_dict_does_not_pollute_downstream(self) -> None:
        """蓝军挑战 1: LLM returns body as dict; must NOT become str(dict) garbage.

        Before HIGH-2 fix: body would become \"{'text': '正文', 'html': '...'}\"
        After fix: extract 'text' subfield → clean string.
        """
        llm_output = {
            "content": {
                "title": "t",
                "body": {"text": "正文内容", "html": "<p>正文</p>", "meta": {"author": "x"}},
            }
        }
        r = CleanerOutput.model_validate(llm_output)
        assert r.content.body == "正文内容"
        # Ensure no Python repr leaked into the body
        assert "{" not in (r.content.body or "")
        assert "html" not in (r.content.body or "")

    def test_content_title_dict_does_not_pollute_downstream(self) -> None:
        """蓝军挑战 1 variant: title as dict must not produce garbage."""
        llm_output = {
            "content": {"title": {"text": "Real Title", "html": "<h1>Title</h1>"}, "body": "b"}
        }
        r = CleanerOutput.model_validate(llm_output)
        assert r.content.title == "Real Title"
        assert "{" not in (r.content.title or "")

    def test_content_list_of_dict_becomes_none(self) -> None:
        """蓝军挑战 3: content=[...] resets to defaults (None), no garbage."""
        llm_output = {"content": [{"title": "a"}, {"body": "b"}]}
        r = CleanerOutput.model_validate(llm_output)
        assert r.content.title is None
        assert r.content.body is None

    def test_all_fields_dict_or_list_no_garbage(self) -> None:
        """Stress: every str field is dict/list; none should produce repr garbage."""
        llm_output = {
            "publish_time": {"date": "2024-01-01", "extra": "noise"},
            "author": {"name": "Author", "extra": "noise"},
            "content": {
                "title": {"text": "Title", "html": "noise"},
                "body": {"text": "Body", "html": "noise"},
                "subtitle": {"text": "Sub"},
                "summary": {"value": "Summary"},
            },
            "tags": [{"bad": "x"}, ["nested"], "valid", 42],
        }
        r = CleanerOutput.model_validate(llm_output)
        assert r.publish_time == "2024-01-01"
        assert r.author == "Author"
        assert r.content.title == "Title"
        assert r.content.body == "Body"
        assert r.content.subtitle == "Sub"
        assert r.content.summary == "Summary"
        assert r.tags == ["valid", "42"]
        # Verify no Python repr strings leaked anywhere
        for val in [
            r.publish_time,
            r.author,
            r.content.title,
            r.content.body,
            r.content.subtitle,
            r.content.summary,
        ]:
            if val is not None:
                assert "{" not in val, f"dict repr leaked into: {val!r}"
                assert "[" not in val, f"list repr leaked into: {val!r}"

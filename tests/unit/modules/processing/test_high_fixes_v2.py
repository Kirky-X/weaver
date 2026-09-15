# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Regression tests for high-priority fixes: processing module.

Covers:
- SpacyExtractor wheel stat failure returns None
- AnalyzeOutput.sentiment_score is clamped to [0, 1]
- EntityExtractor data-metrics filter before relation validation
- NarrativeSchemaExtractor None cleaned state
- SentimentTrackerNode NULL after_avg treated as seed
- ConflictDetector unit extraction + empty attribute guard
- ContentHashCache key separator
- PipelinePersistence per-state terminal accounting
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# AnalyzeOutput range matches prompt + DB CHECK ([0, 1])
# ---------------------------------------------------------------------------


class TestAnalyzeOutputRange:
    def test_negative_sentiment_score_rejected(self):
        from pydantic import ValidationError
        from core.llm.validation.output_validator import AnalyzeOutput

        with pytest.raises(ValidationError):
            AnalyzeOutput(summary="s", sentiment_score=-0.3)

    def test_zero_and_one_accepted(self):
        from core.llm.validation.output_validator import AnalyzeOutput

        assert AnalyzeOutput(summary="s", sentiment_score=0.0).sentiment_score == 0.0
        assert AnalyzeOutput(summary="s", sentiment_score=1.0).sentiment_score == 1.0


# ---------------------------------------------------------------------------
# conflict detector
# ---------------------------------------------------------------------------


class TestConflictDetectorClaims:
    def _node(self):
        from modules.processing.nodes.quality.conflict_detector import ConflictDetectorNode

        return ConflictDetectorNode(article_repo=MagicMock(), vector_repo=None)

    def test_number_unit_claim_real_unit(self):
        claims = self._node()._extract_claims_regex("2023年人口达到3亿人")
        unit_claims = [c for c in claims if c["unit"] == "亿"]
        assert unit_claims, f"expected an 亿-unit claim, got {claims}"

    def test_percent_claim_unit(self):
        claims = self._node()._extract_claims_regex("失业率为5%")
        pct = [c for c in claims if c["unit"] == "%"]
        assert pct

    def test_reach_claim_chinese_unit(self):
        claims = self._node()._extract_claims_regex("销量达到50万台")
        reach = [c for c in claims if c["attribute"] == "reach"]
        assert reach and reach[0]["unit"] == "万"

    def test_empty_attribute_matches_no_synonym_group(self):
        from modules.processing.nodes.quality.conflict_detector import ConflictDetectorNode

        assert ConflictDetectorNode._get_synonym_groups("") == set()

    def test_two_empty_attributes_not_same(self):
        node = self._node()
        a = {"attribute": "", "value": 10}
        b = {"attribute": "", "value": 99}
        assert not node._same_attribute(a, b)


# ---------------------------------------------------------------------------
# content hash separator
# ---------------------------------------------------------------------------


def _raw_article(title: str, body: str):
    from modules.ingestion.domain.models import RawArticle

    return RawArticle(
        url="https://example.com/a",
        title=title,
        body=body,
        source="s",
        publish_time=None,
        source_host="example.com",
    )


class TestContentHashCacheSeparator:
    def test_boundary_collision_eliminated(self):
        from modules.processing.pipeline.content_hash_cache import ContentHashCacheService

        svc = ContentHashCacheService(cache_client=None)

        state_a = {"raw": _raw_article("A", "BC")}
        state_b = {"raw": _raw_article("AB", "C")}

        key_a = svc._snapshot_pair(state_a)[0]
        key_b = svc._snapshot_pair(state_b)[0]
        assert key_a != key_b, "distinct title/body splits must not collide"


# ---------------------------------------------------------------------------
# spacy wheel stat failure
# ---------------------------------------------------------------------------


class TestSpacyWheelStatFailure:
    def test_stat_oserror_returns_none(self, tmp_path):
        from modules.processing.nlp.spacy_extractor import SpacyExtractor

        extractor = SpacyExtractor()
        missing = tmp_path / "gone.whl"
        assert extractor._extract_wheel_safely(str(missing)) is None


# ---------------------------------------------------------------------------
# narrative schema None cleaned
# ---------------------------------------------------------------------------


class TestNarrativeSchemaNoneCleaned:
    @pytest.mark.asyncio
    async def test_none_cleaned_degrades_without_attribute_error(self):
        from modules.processing.nodes.extraction.narrative_schema_extractor import (
            NarrativeSchemaExtractorNode,
        )

        llm = MagicMock()
        llm.call_at = AsyncMock(side_effect=ValueError("llm invalid output"))
        budget = MagicMock()
        budget.truncate.return_value = "body"
        prompt_loader = MagicMock()
        graph_writer = MagicMock()

        node = NarrativeSchemaExtractorNode(
            llm=llm,
            budget=budget,
            prompt_loader=prompt_loader,
            graph_writer=graph_writer,
        )
        node._record_prompt_version = MagicMock()

        raw = SimpleNamespace(url="https://example.com/a")
        state = {
            "terminal": False,
            "is_merged": False,
            "cleaned": None,  # explicitly None — previously AttributeError
            "entities": [],
            "article_id": None,
            "raw": raw,
        }

        result = await node.execute(state)
        assert "degraded_fields" in result or result is state


# ---------------------------------------------------------------------------
# sentiment tracker NULL after_avg
# ---------------------------------------------------------------------------


class TestSentimentTrackerNullAfterAvg:
    @pytest.mark.asyncio
    async def test_none_after_avg_seeded_not_crash(self):
        from modules.processing.nodes.extraction.sentiment_tracker import SentimentTrackerNode

        shift_repo = MagicMock()
        shift_repo.get_last_article_shift = AsyncMock(
            return_value={"after_avg": None}  # storage returns NULL column
        )
        shift_repo.save_shift = AsyncMock()

        node = SentimentTrackerNode(shift_repo=shift_repo)
        await node._track_single_entity("art-1", "美联储", 0.6)

        record = shift_repo.save_shift.await_args.args[0]
        assert record["before_avg"] == 0.6
        assert record["shift_value"] == 0.0
        assert record["direction"] == "stable"


def LambdaMock(spacy_entities, gliner_entities):
    """Mimic EntityExtractorNode._prepare_llm_entities for fake_self tests."""
    all_spacy = [{"name": e.name, "type": e.type, "label": e.label} for e in spacy_entities]
    all_gliner = [
        {"name": e["text"], "type": e["type"], "label": e["type"]} for e in gliner_entities
    ]
    return all_spacy + all_gliner


# ---------------------------------------------------------------------------
# data-metrics filter before relation validation
# ---------------------------------------------------------------------------


class TestEntityFilterBeforeRelationValidation:
    @pytest.mark.asyncio
    async def test_dangling_relations_dropped(self):
        from modules.processing.nodes.extraction.entity_extractor import EntityExtractorNode

        output = SimpleNamespace(
            entities=[
                {"name": "美联储", "type": "机构"},
                {"name": "3亿", "type": "数据指标"},
            ],
            relations=[
                {"source": "美联储", "target": "3亿", "relation_type": "RELATED"},
                {"source": "美联储", "target": "美联储", "relation_type": "RELATED"},
            ],
        )
        llm = MagicMock()
        llm.call_at = AsyncMock(return_value=output)
        budget = MagicMock()
        budget.truncate.return_value = "body"

        fake_self = SimpleNamespace(
            _llm=llm,
            _budget=budget,
            _relation_type_normalizer=None,
            _persist_and_cleanup_entity_vectors=AsyncMock(),
            _prepare_relation_types_block=AsyncMock(return_value=""),
            _normalize_relation_types=AsyncMock(),
            _prepare_llm_entities=LambdaMock,
            _validate_and_clean_entities_relations=(
                EntityExtractorNode._validate_and_clean_entities_relations
            ),
        )

        state = {"entities": [], "relations": [], "raw": SimpleNamespace(url="https://e.com/a")}
        await EntityExtractorNode._llm_refine_and_validate(
            fake_self, state, "body", True, [], [], {}
        )

        assert [e["name"] for e in state["entities"]] == ["美联储"]
        # Relation pointing at the filtered 数据指标 entity must be dropped.
        assert len(state["relations"]) == 1


# ---------------------------------------------------------------------------
# per-state terminal accounting
# ---------------------------------------------------------------------------


def _terminal_state(url: str):
    return {"terminal": True, "raw": SimpleNamespace(url=url)}


class TestTerminalStateAccounting:
    @pytest.mark.asyncio
    async def test_partial_failure_counts_accurately(self):
        from modules.processing.pipeline.persistence import PipelinePersistence

        article_repo = MagicMock()
        call_count = {"n": 0}

        async def mark_terminal(url):
            return False

        async def bulk_upsert(states):
            call_count["n"] += 1
            if call_count["n"] == 2:  # second insert fails
                raise RuntimeError("db down")
            return [SimpleNamespace(id=1)]

        article_repo.mark_terminal_by_url = AsyncMock(side_effect=mark_terminal)
        article_repo.bulk_upsert = AsyncMock(side_effect=bulk_upsert)

        persistence = PipelinePersistence(
            article_repo=article_repo,
            vector_repo=None,
            graph_writer=None,
            phase3_concurrency=1,
        )
        completed, failed = await persistence._handle_terminal_states(
            [_terminal_state(f"https://e.com/{i}") for i in range(5)]
        )

        assert (completed, failed) == (4, 1), "partial failure must be counted per state"

    @pytest.mark.asyncio
    async def test_all_success(self):
        from modules.processing.pipeline.persistence import PipelinePersistence

        article_repo = MagicMock()
        article_repo.mark_terminal_by_url = AsyncMock(return_value=True)

        persistence = PipelinePersistence(
            article_repo=article_repo,
            vector_repo=None,
            graph_writer=None,
            phase3_concurrency=1,
        )
        completed, failed = await persistence._handle_terminal_states(
            [_terminal_state("https://e.com/a"), _terminal_state("https://e.com/b")]
        )
        assert (completed, failed) == (2, 0)

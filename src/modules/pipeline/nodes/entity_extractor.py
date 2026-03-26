# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Entity extractor pipeline node — spaCy + batch embed + LLM refinement."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from core.llm.client import LLMClient
from core.llm.output_validator import EntityExtractorOutput
from core.llm.token_budget import TokenBudgetManager
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from core.prompt.loader import PromptLoader
from modules.nlp.spacy_extractor import SpacyExtractor
from modules.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.protocols import VectorRepository

log = get_logger("node.entity_extractor")

# Patterns for filtering meaningless entities
# Chinese year pattern: 2012年, 2025年, etc.
YEAR_PATTERN = re.compile(r"^\d{2,4}年$")
# Chinese date pattern: 4月23日, 12月31日, etc.
CHINESE_DATE_PATTERN = re.compile(r"^\d{1,2}月\d{1,2}[日号]?$")
# Pure time pattern: 3小时前, 2天前, etc.
TIME_PATTERN = re.compile(r"^\d+[小时分钟天周月年]前$")
# Pure number pattern: 97, 3.14, etc.
PURE_NUMBER_PATTERN = re.compile(r"^\d+\.?\d*$")
# Number with units: 5.56元, 12.0%, etc.
NUMBER_WITH_UNIT_PATTERN = re.compile(r"^[\d.]+[元%$‰°]?$")
# Percentage: 121.26%, 50%, etc.
PERCENTAGE_PATTERN = re.compile(r"^[\d.]+%$")

# Entity types that should be completely filtered out (no meaningful value)
BANNED_ENTITY_TYPES = frozenset(
    {
        "数据指标",
        "数量",
        "金额",
        "百分比",
    }
)

# Time-related entity types
TIME_ENTITY_TYPES = frozenset(
    {
        "时间",
        "DATE",
        "TIME",
    }
)


def is_meaningful_entity(name: str, entity_type: str) -> bool:
    """Check if an entity is meaningful and should be kept.

    Filters out meaningless entities such as:
    - Pure numbers (e.g., "97", "3.14")
    - Pure dates (e.g., "2012年", "4月23日")
    - Pure times (e.g., "3小时前")
    - Entities with only numbers and symbols (e.g., "5.56元", "12.0%")
    - Time entities that are just year/date references without context

    Args:
        name: The entity name to check.
        entity_type: The entity type (e.g., "人物", "组织机构", "时间").

    Returns:
        True if the entity is meaningful, False if it should be filtered out.
    """
    # Strip whitespace
    name = name.strip()

    # Filter out very short entities (< 2 characters)
    if len(name) < 2:
        return False

    # Filter out banned entity types completely
    if entity_type in BANNED_ENTITY_TYPES:
        log.debug(
            "entity_filtered_banned_type",
            name=name,
            entity_type=entity_type,
        )
        return False

    # Filter out data indicators/percentages
    if PERCENTAGE_PATTERN.match(name):
        log.debug(
            "entity_filtered_percentage",
            name=name,
        )
        return False

    if NUMBER_WITH_UNIT_PATTERN.match(name):
        log.debug(
            "entity_filtered_number_with_unit",
            name=name,
        )
        return False

    # Filter out pure numbers
    if PURE_NUMBER_PATTERN.match(name):
        log.debug(
            "entity_filtered_pure_number",
            name=name,
        )
        return False

    # For time-related types, be more selective
    if entity_type in TIME_ENTITY_TYPES:
        # Keep meaningful time references like "今天", "今日", "本周", "本月"
        # But filter out pure year references like "2012年", "2025年"
        if YEAR_PATTERN.match(name):
            log.debug(
                "entity_filtered_year",
                name=name,
            )
            return False

        # Filter out Chinese date patterns like "4月23日"
        if CHINESE_DATE_PATTERN.match(name):
            log.debug(
                "entity_filtered_chinese_date",
                name=name,
            )
            return False

        # Filter out time offset patterns like "3小时前"
        if TIME_PATTERN.match(name):
            log.debug(
                "entity_filtered_time_offset",
                name=name,
            )
            return False

    return True


class EntityExtractorNode:
    """Pipeline node: extract entities using spaCy + LLM refinement.

    Three-phase extraction:
    1. spaCy NER (language-routed, run in executor to avoid blocking).
    2. Batch embedding of entities for vector storage.
    3. LLM refinement and relation extraction.
    """

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
        spacy: SpacyExtractor,
        vector_repo: VectorRepository | None = None,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._spacy = spacy
        self._vector_repo = vector_repo

    async def execute(self, state: PipelineState) -> PipelineState:
        """Extract entities and relations."""
        if state.get("terminal") or state.get("is_merged"):
            return state

        body = state["cleaned"]["body"]
        language = state.get("language", "zh")

        # Phase 1: spaCy NER (sync, run in executor)
        try:
            loop = asyncio.get_running_loop()
            spacy_entities = await loop.run_in_executor(None, self._spacy.extract, body, language)
        except Exception as e:
            log.warning("spacy_extraction_failed_using_empty", error=str(e), url=state["raw"].url)
            spacy_entities = []

        # Phase 2: Batch embed entities
        entity_name_to_embedding: dict[str, list[float]] = {}
        if spacy_entities:
            try:
                entity_texts = [f"{e.name}（{e.type}）" for e in spacy_entities]
                entity_embeds = await self._llm.batch_embed(entity_texts)

                for i, e in enumerate(spacy_entities):
                    if i < len(entity_embeds) and entity_embeds[i]:
                        entity_name_to_embedding[e.name] = entity_embeds[i]

                if self._vector_repo:
                    try:
                        # Use temp keys for entity vectors - the actual UUIDs will be
                        # set by neo4j_writer after entity creation
                        await self._vector_repo.upsert_entity_vectors(
                            list(
                                zip(
                                    [e.name for e in spacy_entities],
                                    entity_embeds,
                                )
                            ),
                            use_temp_key=True,
                        )
                    except Exception as exc:
                        log.warning("entity_vector_upsert_failed", error=str(exc))
            except Exception as e:
                log.warning("entity_embedding_failed", error=str(e))

        # Phase 3: LLM refinement
        body_trunc = self._budget.truncate(body, CallPoint.ENTITY_EXTRACTOR)
        try:
            result: EntityExtractorOutput = await self._llm.call(
                CallPoint.ENTITY_EXTRACTOR,
                {
                    "body": body_trunc,
                    "spacy_entities": [
                        {
                            "name": e.name,
                            "type": e.type,
                            "label": e.label,
                        }
                        for e in spacy_entities
                    ],
                    "article_id": state.get("article_id"),
                    "task_id": state.get("task_id"),
                },
                output_model=EntityExtractorOutput,
            )

            # Filter out meaningless entities before storing in state
            filtered_entities = []
            for entity in result.entities:
                name = entity.get("name", "")
                entity_type = entity.get("type", "")
                if is_meaningful_entity(name, entity_type):
                    filtered_entities.append(entity)
                else:
                    log.debug(
                        "entity_filtered",
                        name=name,
                        entity_type=entity_type,
                        url=state["raw"].url,
                    )

            # Filter relations to only include entities that passed the filter
            valid_entity_names = {e.get("name") for e in filtered_entities}
            filtered_relations = [
                r
                for r in result.relations
                if r.get("source") in valid_entity_names and r.get("target") in valid_entity_names
            ]

            state["entities"] = filtered_entities
            state["relations"] = filtered_relations
            entity_count = len(filtered_entities)

            for entity in state["entities"]:
                name = entity.get("name", "")
                if name in entity_name_to_embedding:
                    entity["embedding"] = entity_name_to_embedding[name]

        except Exception as e:
            log.warning("entity_llm_failed_using_empty", error=str(e), url=state["raw"].url)
            state["entities"] = []
            state["relations"] = []
            entity_count = 0

        state.setdefault("prompt_versions", {})["entity_extractor"] = (
            self._prompt_loader.get_version("entity_extractor")
        )

        log.info(
            "entities_extracted",
            url=state["raw"].url,
            entity_count=entity_count,
            relation_count=len(state["relations"]),
        )
        return state

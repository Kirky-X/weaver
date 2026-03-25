# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Entity extractor pipeline node — spaCy + batch embed + LLM refinement."""

from __future__ import annotations

import asyncio
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
                        await self._vector_repo.upsert_entity_vectors(
                            list(
                                zip(
                                    [e.name for e in spacy_entities],
                                    entity_embeds,
                                )
                            )
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
            state["entities"] = result.entities
            state["relations"] = result.relations
            entity_count = len(result.entities)

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

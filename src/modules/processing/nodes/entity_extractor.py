# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Entity extractor pipeline node — spaCy + batch embed + LLM refinement."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from core.llm.client import LLMClient
from core.llm.output_validator import EntityExtractorOutput
from core.llm.token_budget import TokenBudgetManager
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from core.prompt.loader import PromptLoader
from modules.processing.nlp.spacy_extractor import SpacyExtractor
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from modules.knowledge.core.relation_types import RelationTypeNormalizer

log = get_logger("node.entity_extractor")

# Default relation types when normalizer is not available
_DEFAULT_RELATION_TYPES = """
任职于: 某人在某组织担任职务
隶属于: 某组织隶属于另一组织
位于: 某实体位于某地理位置
参与: 某实体参与某事件或活动
发布: 某实体发布某内容或产品
签署: 某实体签署某协议或文件
收购: 某实体收购另一实体
合作: 实体之间的合作关系
监管: 某实体监管另一实体
竞争: 实体之间的竞争关系
""".strip()


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
        vector_repo: Any = None,
        relation_type_normalizer: RelationTypeNormalizer | None = None,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._spacy = spacy
        self._vector_repo = vector_repo
        self._relation_type_normalizer = relation_type_normalizer

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
                entity_embeds = await self._llm.embed(
                    "embedding.aiping_embedding.Qwen3-Embedding-0.6B", entity_texts
                )

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

        # Build relation types block for prompt
        relation_types_block = _DEFAULT_RELATION_TYPES
        if self._relation_type_normalizer:
            try:
                active_types = await self._relation_type_normalizer.get_all_active()
                if active_types:
                    lines = []
                    for rt in active_types:
                        # Format: "type_name: description" or "type_name" if no description
                        line = rt.name if rt.name else rt.raw_type
                        if rt.description:
                            line = f"{line}: {rt.description}"
                        lines.append(line)
                    relation_types_block = "\n".join(lines)
            except Exception as e:
                log.warning("relation_type_fetch_failed_using_default", error=str(e))

        try:
            result: EntityExtractorOutput = await self._llm.call_at(
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
                    "relation_types_block": relation_types_block,
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

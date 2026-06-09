# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Entity extractor pipeline node — spaCy + batch embed + LLM refinement."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from core.llm.client import LLMClient
from core.llm.config.token_budget import TokenBudgetManager
from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import EntityExtractorOutput
from core.observability.logging import get_logger
from core.prompt.loader import PromptLoader
from modules.processing.nlp.spacy_extractor import SpacyExtractor
from modules.processing.nodes.extraction.gliner_extractor import GLiNERExtractor
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from config.settings import Settings
    from modules.knowledge.graph.relation_type_normalizer import RelationTypeNormalizer

log = get_logger(__name__)

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
        settings: Settings | None = None,
        vector_repo: Any = None,
        relation_type_normalizer: RelationTypeNormalizer | None = None,
        gliner_extractor: GLiNERExtractor | None = None,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._spacy = spacy
        self._settings = settings
        self._vector_repo = vector_repo
        self._relation_type_normalizer = relation_type_normalizer
        self._gliner_extractor = gliner_extractor

    async def execute(self, state: PipelineState) -> PipelineState:
        """Extract entities and relations."""
        if state.get("terminal") or state.get("is_merged"):
            return state

        body = state["cleaned"]["body"]
        language = state.get("language", "zh")

        # Phase 1: spaCy NER (sync, run in executor)
        disable_data_metrics = (
            self._settings.entity.disable_data_metrics_nodes if self._settings else False
        )
        try:
            loop = asyncio.get_running_loop()
            spacy_entities = await loop.run_in_executor(
                None,
                lambda: self._spacy.extract(body, language, disable_data_metrics),
            )
        except (OSError, RuntimeError, Exception) as e:
            log.warning(
                "spacy_extraction_failed_using_empty",
                exc_type=type(e).__name__,
                error=str(e),
                url=state["raw"].url,
            )
            spacy_entities = []

        # Phase 1.5: GLiNER zero-shot extraction (if available)
        gliner_entities = []
        if self._gliner_extractor and self._gliner_extractor._config.enabled:
            try:
                gliner_entities = await self._gliner_extractor.extract_entities(body)
                log.debug(
                    "gliner_extraction_completed",
                    entity_count=len(gliner_entities),
                    url=state["raw"].url,
                )
            except Exception as e:
                log.warning(
                    "gliner_extraction_failed",
                    exc_type=type(e).__name__,
                    error=str(e),
                    url=state["raw"].url,
                )

        # Phase 2: Batch embed entities
        entity_name_to_embedding: dict[str, list[float]] = {}
        if spacy_entities or gliner_entities:
            try:
                # Combine spaCy and GLiNER entities for embedding
                all_entity_texts = []
                all_entity_names = []

                # Add spaCy entities
                for e in spacy_entities:
                    all_entity_texts.append(f"{e.name}（{e.type}）")
                    all_entity_names.append(e.name)

                # Add GLiNER entities (convert to same format)
                for e in gliner_entities:
                    all_entity_texts.append(f"{e['text']}（{e['type']}）")
                    all_entity_names.append(e["text"])

                if all_entity_texts:
                    entity_embeds = await self._llm.embed_default(all_entity_texts)

                    for i, name in enumerate(all_entity_names):
                        if i < len(entity_embeds) and entity_embeds[i]:
                            entity_name_to_embedding[name] = entity_embeds[i]

                    if self._vector_repo:
                        try:
                            # Get embedding model from settings
                            model_id = (
                                self._settings.llm.embedding_model
                                if self._settings
                                else "Qwen3-Embedding-0.6B"
                            )
                            await self._vector_repo.upsert_entity_vectors(
                                list(
                                    zip(
                                        all_entity_names,
                                        entity_embeds,
                                    )
                                ),
                                model_id=model_id,
                            )
                        except Exception as exc:
                            log.warning(
                                "entity_vector_upsert_failed",
                                exc_type=type(exc).__name__,
                                error=str(exc),
                            )
            except (AllProvidersFailedError, CircuitOpenError, ValueError, Exception) as e:
                log.warning(
                    "entity_embedding_failed",
                    exc_type=type(e).__name__,
                    error=str(e),
                )

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
                log.warning(
                    "relation_type_fetch_failed_using_default",
                    exc_type=type(e).__name__,
                    error=str(e),
                )

        try:
            # Combine spaCy and GLiNER entities for LLM input
            all_spacy_entities = [
                {
                    "name": e.name,
                    "type": e.type,
                    "label": e.label,
                }
                for e in spacy_entities
            ]
            # Convert GLiNER entities to same format
            gliner_entities_for_llm = [
                {
                    "name": e["text"],
                    "type": e["type"],
                    "label": e["type"],
                }
                for e in gliner_entities
            ]
            all_entities_for_llm = all_spacy_entities + gliner_entities_for_llm

            result: EntityExtractorOutput = await self._llm.call_at(
                CallPoint.ENTITY_EXTRACTOR,
                {
                    "body": body_trunc,
                    "spacy_entities": all_entities_for_llm,
                    "article_id": state.get("article_id"),
                    "task_id": state.get("task_id"),
                    "relation_types_block": relation_types_block,
                },
                output_model=EntityExtractorOutput,
            )
            state["entities"] = result.entities
            state["relations"] = result.relations
            entity_count = len(result.entities)

            # Filter data metrics entities when configured
            if disable_data_metrics:
                state["entities"] = [e for e in state["entities"] if e.get("type") != "数据指标"]
                entity_count = len(state["entities"])

            # Attach embeddings from spaCy phase
            for entity in state["entities"]:
                name = entity.get("name", "")
                if name in entity_name_to_embedding:
                    entity["embedding"] = entity_name_to_embedding[name]

            # Phase 4: Embed and persist LLM-extracted entities that don't have embeddings yet
            # This handles the case where spaCy failed but LLM still extracted entities
            if self._vector_repo and state["entities"]:
                entities_need_embedding = [
                    e for e in state["entities"] if not e.get("embedding") and e.get("name")
                ]
                if entities_need_embedding:
                    try:
                        entity_texts = [
                            f"{e['name']}（{e.get('type', '未知')}）"
                            for e in entities_need_embedding
                        ]
                        entity_embeds = await self._llm.embed_default(entity_texts)

                        # Update entities with embeddings
                        entity_vectors_to_upsert = []
                        for i, entity in enumerate(entities_need_embedding):
                            if i < len(entity_embeds) and entity_embeds[i]:
                                entity["embedding"] = entity_embeds[i]
                                # Use canonical_name if available, otherwise name
                                key = entity.get("canonical_name") or entity.get("name")
                                if key:
                                    entity_vectors_to_upsert.append((key, entity_embeds[i]))

                        # Persist to database
                        if entity_vectors_to_upsert:
                            # Get embedding model from settings
                            model_id = (
                                self._settings.llm.embedding_model
                                if self._settings
                                else "Qwen3-Embedding-0.6B"
                            )
                            await self._vector_repo.upsert_entity_vectors(
                                entity_vectors_to_upsert,
                                model_id=model_id,
                            )
                            log.debug(
                                "entity_vectors_persisted",
                                count=len(entity_vectors_to_upsert),
                            )
                    except Exception as exc:
                        log.warning(
                            "llm_entity_embedding_failed",
                            exc_type=type(exc).__name__,
                            error=str(exc),
                        )

            # Phase 5: Clean up filtered entities from entity_vectors
            # Remove entities that were extracted by spaCy/GLiNER but filtered out by LLM
            if self._vector_repo and (spacy_entities or gliner_entities):
                spacy_names = {e.name for e in spacy_entities}
                gliner_names = {e["text"] for e in gliner_entities}
                all_extracted_names = spacy_names | gliner_names
                llm_names = {
                    e.get("canonical_name") or e.get("name")
                    for e in state["entities"]
                    if e.get("name")
                }
                filtered_names = list(all_extracted_names - llm_names)
                if filtered_names:
                    try:
                        deleted = await self._vector_repo.delete_entity_vectors_by_neo4j_ids(
                            filtered_names
                        )
                        if deleted > 0:
                            log.debug(
                                "entity_vectors_cleaned",
                                deleted=deleted,
                                filtered_entities=filtered_names[:10],  # Log first 10
                            )
                    except Exception as exc:
                        log.warning(
                            "entity_vectors_cleanup_failed",
                            exc_type=type(exc).__name__,
                            error=str(exc),
                        )

        except (AllProvidersFailedError, CircuitOpenError, ValueError, Exception) as e:
            log.warning(
                "entity_llm_failed_using_empty",
                exc_type=type(e).__name__,
                error=str(e),
                url=state["raw"].url,
            )
            state["entities"] = []
            state["relations"] = []
            entity_count = 0
            # Mark degraded fields
            state.setdefault("degraded_fields", []).extend(["entities", "relations"])
            state.setdefault("degradation_reasons", {}).update(
                {
                    "entities": f"LLM entity extraction failed: {e!s}",
                    "relations": f"LLM entity extraction failed: {e!s}",
                }
            )

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

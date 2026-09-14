# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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
from core.observability import get_logger
from core.constants import EmbeddingModel
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

ALLOWED_ENTITY_TYPES = {
    "人物",
    "组织机构",
    "地点",
    "产品与技术",
    "事件",
    "数据指标",
    "法规与政策",
    "未知",
}

# LLM 偶尔返回简写或近义类型，映射到 ALLOWED_ENTITY_TYPES 标准名称。
# 防御性 fallback，prompt 已统一为标准名称（规则8 惯例优先）。
_ENTITY_TYPE_ALIASES: dict[str, str] = {
    "产品": "产品与技术",
    "技术": "产品与技术",
    "概念": "产品与技术",
    "组织": "组织机构",
    "机构": "组织机构",
    "公司": "组织机构",
    "企业": "组织机构",
    "政策": "法规与政策",
    "法规": "法规与政策",
    "法律": "法规与政策",
    "指标": "数据指标",
}


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

        disable_data_metrics = (
            self._settings.entity.disable_data_metrics_nodes if self._settings else False
        )
        spacy_entities = await self._extract_spacy_entities(state, body, language)
        gliner_entities = await self._extract_gliner_entities(state, body)
        entity_name_to_embedding = await self._embed_and_store_entities(
            state, spacy_entities, gliner_entities
        )
        await self._llm_refine_and_validate(
            state,
            body,
            disable_data_metrics,
            spacy_entities,
            gliner_entities,
            entity_name_to_embedding,
        )

        state.setdefault("prompt_versions", {})["entity_extractor"] = (
            self._prompt_loader.get_version("entity_extractor")
        )

        log.info(
            "entities_extracted",
            url=state["raw"].url,
            entity_count=len(state.get("entities") or []),
            relation_count=len(state.get("relations") or []),
        )
        return state

    async def _extract_spacy_entities(self, state: PipelineState, body: str, language: str):
        """Phase 1: spaCy NER (sync, run in executor)."""
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
        return spacy_entities

    async def _extract_gliner_entities(self, state: PipelineState, body: str):
        """Phase 1.5: GLiNER zero-shot extraction (if available)."""
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
        return gliner_entities

    async def _embed_and_store_entities(
        self, state: PipelineState, spacy_entities: list, gliner_entities: list
    ):
        """Phase 2: batch-embed extracted entities and upsert entity vectors."""
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
                    entity_embeds = await self._llm.embed_default(
                        all_entity_texts,
                        article_id=state.get("article_id"),
                        task_id=state.get("task_id"),
                    )

                    for i, name in enumerate(all_entity_names):
                        if i < len(entity_embeds) and entity_embeds[i]:
                            entity_name_to_embedding[name] = entity_embeds[i]

                    if self._vector_repo:
                        try:
                            model_id = (
                                self._llm.default_embedding_label
                                if self._llm
                                else EmbeddingModel.DEFAULT
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
        return entity_name_to_embedding

    async def _llm_refine_and_validate(
        self,
        state: PipelineState,
        body: str,
        disable_data_metrics: bool,
        spacy_entities: list,
        gliner_entities: list,
        entity_name_to_embedding: dict[str, list[float]],
    ):
        """Phases 3-5: LLM refinement, normalization, validation, vector cleanup."""
        body_trunc = self._budget.truncate(body, CallPoint.ENTITY_EXTRACTOR)
        relation_types_block = await self._prepare_relation_types_block()

        try:
            all_entities_for_llm = self._prepare_llm_entities(spacy_entities, gliner_entities)

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
                article_id=state.get("article_id"),
                task_id=state.get("task_id"),
            )
            state["entities"] = result.entities
            state["relations"] = result.relations

            # Normalize relation types
            await self._normalize_relation_types(state)

            # Post-validation: entity types + relation integrity
            self._validate_and_clean_entities_relations(state)

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

            # Phase 4+5: Persist new entity vectors + clean up filtered ones
            await self._persist_and_cleanup_entity_vectors(
                state,
                spacy_entities,
                gliner_entities,
            )

        except (AllProvidersFailedError, CircuitOpenError, ValueError, Exception) as e:
            log.warning(
                "entity_llm_failed_using_empty",
                exc_type=type(e).__name__,
                error=str(e),
                url=state["raw"].url,
            )
            import traceback as _tb

            _tb.print_exc()
            state["entities"] = []
            state["relations"] = []
            entity_count = 0
            state.setdefault("degraded_fields", []).extend(["entities", "relations"])
            state.setdefault("degradation_reasons", {}).update(
                {
                    "entities": f"LLM entity extraction failed: {e!s}",
                    "relations": f"LLM entity extraction failed: {e!s}",
                }
            )

    async def _prepare_relation_types_block(self) -> str:
        """Fetch active relation types or fall back to default block."""
        if not self._relation_type_normalizer:
            return _DEFAULT_RELATION_TYPES
        try:
            active_types = await self._relation_type_normalizer.get_all_active()
            if active_types:
                lines = []
                for rt in active_types:
                    line = rt.name if rt.name else rt.raw_type
                    if rt.description:
                        line = f"{line}: {rt.description}"
                    lines.append(line)
                return "\n".join(lines)
        except Exception as e:
            log.warning(
                "relation_type_fetch_failed_using_default",
                exc_type=type(e).__name__,
                error=str(e),
            )
        return _DEFAULT_RELATION_TYPES

    @staticmethod
    def _prepare_llm_entities(spacy_entities: list, gliner_entities: list) -> list[dict]:
        """Convert spaCy + GLiNER entities to uniform LLM input format."""
        all_spacy = [{"name": e.name, "type": e.type, "label": e.label} for e in spacy_entities]
        all_gliner = [
            {"name": e["text"], "type": e["type"], "label": e["type"]} for e in gliner_entities
        ]
        return all_spacy + all_gliner

    async def _normalize_relation_types(self, state: PipelineState) -> None:
        """Normalize relation type names via the normalizer (if available)."""
        if not self._relation_type_normalizer:
            return
        normalized = []
        for rel in state["relations"]:
            raw_type = rel.get("relation_type", "")
            try:
                result = await self._relation_type_normalizer.normalize(raw_type)
                if result.name:
                    rel["relation_type"] = result.name
            except Exception as e:
                log.warning("relation_type_normalize_failed", raw_type=raw_type, error=str(e))
            normalized.append(rel)
        state["relations"] = normalized

    @staticmethod
    def _validate_and_clean_entities_relations(state: PipelineState) -> None:
        """Validate entity types (alias + allowed set) and drop orphan relations."""
        for entity in state["entities"]:
            entity_type = entity.get("type", "未知")
            if entity_type in _ENTITY_TYPE_ALIASES:
                log.debug(
                    "entity_type_alias_mapped",
                    entity_name=entity.get("name", ""),
                    original_type=entity_type,
                    mapped_type=_ENTITY_TYPE_ALIASES[entity_type],
                )
                entity_type = _ENTITY_TYPE_ALIASES[entity_type]
            if entity_type not in ALLOWED_ENTITY_TYPES:
                log.warning(
                    "entity_type_not_allowed",
                    entity_name=entity.get("name", ""),
                    original_type=entity.get("type", ""),
                    mapped_type="未知",
                )
                entity_type = "未知"
            entity["type"] = entity_type

        entity_names = {e.get("name") for e in state["entities"]}
        valid_relations = []
        for rel in state["relations"]:
            source = rel.get("source")
            target = rel.get("target")
            if source in entity_names and target in entity_names:
                valid_relations.append(rel)
            else:
                log.warning(
                    "relation_dropped_missing_entity",
                    source=source,
                    target=target,
                    relation_type=rel.get("type", ""),
                )
        state["relations"] = valid_relations

    async def _persist_and_cleanup_entity_vectors(
        self,
        state: PipelineState,
        spacy_entities: list,
        gliner_entities: list,
    ) -> None:
        """Phase 4+5: Embed new LLM entities + clean up filtered vectors."""
        # Phase 4: Embed and persist LLM-extracted entities without embeddings
        if self._vector_repo and state["entities"]:
            entities_need_embedding = [
                e for e in state["entities"] if not e.get("embedding") and e.get("name")
            ]
            if entities_need_embedding:
                try:
                    entity_texts = [
                        f"{e['name']}（{e.get('type', '未知')}）" for e in entities_need_embedding
                    ]
                    entity_embeds = await self._llm.embed_default(
                        entity_texts,
                        article_id=state.get("article_id"),
                        task_id=state.get("task_id"),
                    )
                    entity_vectors_to_upsert = []
                    for i, entity in enumerate(entities_need_embedding):
                        if i < len(entity_embeds) and entity_embeds[i]:
                            entity["embedding"] = entity_embeds[i]
                            key = entity.get("canonical_name") or entity.get("name")
                            if key:
                                entity_vectors_to_upsert.append((key, entity_embeds[i]))
                    if entity_vectors_to_upsert:
                        model_id = (
                            self._llm.default_embedding_label
                            if self._llm
                            else EmbeddingModel.DEFAULT
                        )
                        await self._vector_repo.upsert_entity_vectors(
                            entity_vectors_to_upsert,
                            model_id=model_id,
                        )
                        log.debug("entity_vectors_persisted", count=len(entity_vectors_to_upsert))
                except Exception as exc:
                    log.warning(
                        "llm_entity_embedding_failed",
                        exc_type=type(exc).__name__,
                        error=str(exc),
                    )

        # Phase 5: Clean up filtered entity vectors
        if self._vector_repo and (spacy_entities or gliner_entities):
            spacy_names = {e.name for e in spacy_entities}
            gliner_names = {e["text"] for e in gliner_entities}
            all_extracted_names = spacy_names | gliner_names
            llm_names = {
                e.get("canonical_name") or e.get("name") for e in state["entities"] if e.get("name")
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
                            filtered_entities=filtered_names[:10],
                        )
                except Exception as exc:
                    log.warning(
                        "entity_vectors_cleanup_failed",
                        exc_type=type(exc).__name__,
                        error=str(exc),
                    )

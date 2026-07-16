# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for Pipeline ML component pass-through (3.1) and Container ML init (3.2).

Task 3.1 — Verify that Pipeline.__init__ passes cascade_classifier, gliner_extractor,
and mc_sampler through to their respective nodes.

Task 3.2 — Verify that Container.init_ml_components() gracefully degrades when
ML model loading fails (fasttext, GLiNER) and logs warnings.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.processing.pipeline.deps import (
    PipelineAnalyzers,
    PipelineDeps,
    PipelineNlpTools,
)

# ---------------------------------------------------------------------------
# Task 3.1 — Pipeline ML component pass-through tests
# ---------------------------------------------------------------------------


class TestCascadeClassifierNodeReceivesCascade:
    """CascadeClassifierNode should receive the cascade parameter from Pipeline."""

    @patch("modules.processing.pipeline.graph.CascadeClassifierNode")
    @patch("modules.processing.pipeline.graph.CascadeCategorizerNode")
    @patch("modules.processing.pipeline.graph.CleanerNode")
    @patch("modules.processing.pipeline.graph.VectorizeNode")
    @patch("modules.processing.pipeline.graph.BatchMergerNode")
    @patch("modules.processing.pipeline.graph.ReVectorizeNode")
    @patch("modules.processing.pipeline.graph.AnalyzeNode")
    @patch("modules.processing.pipeline.graph.RuleBasedQualityScorerNode")
    @patch("modules.processing.pipeline.graph.RuleBasedCredibilityCheckerNode")
    @patch("modules.processing.pipeline.graph.EntityExtractorNode")
    @patch("modules.processing.pipeline.graph.ConflictDetectorNode")
    @patch("modules.processing.pipeline.graph.CheckpointCleanupNode")
    def test_cascade_passed_to_classifier_node(
        self,
        _mock_checkpoint,
        _mock_conflict,
        _mock_entity,
        _mock_credibility,
        _mock_quality,
        _mock_analyze,
        _mock_re_vectorize,
        _mock_batch_merger,
        _mock_vectorize,
        _mock_cleaner,
        _mock_categorizer,
        _mock_classifier,
    ):
        """When Pipeline is constructed with cascade_classifier, CascadeClassifierNode
        should be initialized with cascade=some_cascade."""
        from modules.processing.pipeline.graph import Pipeline

        mock_cascade = MagicMock(name="CascadeClassifier")
        mock_llm = MagicMock()
        mock_budget = MagicMock()
        mock_prompt_loader = MagicMock()
        mock_event_bus = MagicMock()

        Pipeline(
            deps=PipelineDeps(
                llm=mock_llm,
                budget=mock_budget,
                prompt_loader=mock_prompt_loader,
                event_bus=mock_event_bus,
                analyzers=PipelineAnalyzers(cascade_classifier=mock_cascade),
            ),
        )

        _mock_classifier.assert_called_once_with(
            mock_llm, mock_budget, mock_prompt_loader, cascade=mock_cascade
        )


class TestCascadeCategorizerNodeReceivesCascade:
    """CascadeCategorizerNode should receive the cascade parameter from Pipeline."""

    @patch("modules.processing.pipeline.graph.CascadeClassifierNode")
    @patch("modules.processing.pipeline.graph.CascadeCategorizerNode")
    @patch("modules.processing.pipeline.graph.CleanerNode")
    @patch("modules.processing.pipeline.graph.VectorizeNode")
    @patch("modules.processing.pipeline.graph.BatchMergerNode")
    @patch("modules.processing.pipeline.graph.ReVectorizeNode")
    @patch("modules.processing.pipeline.graph.AnalyzeNode")
    @patch("modules.processing.pipeline.graph.RuleBasedQualityScorerNode")
    @patch("modules.processing.pipeline.graph.RuleBasedCredibilityCheckerNode")
    @patch("modules.processing.pipeline.graph.EntityExtractorNode")
    @patch("modules.processing.pipeline.graph.ConflictDetectorNode")
    @patch("modules.processing.pipeline.graph.CheckpointCleanupNode")
    def test_cascade_passed_to_categorizer_node(
        self,
        _mock_checkpoint,
        _mock_conflict,
        _mock_entity,
        _mock_credibility,
        _mock_quality,
        _mock_analyze,
        _mock_re_vectorize,
        _mock_batch_merger,
        _mock_vectorize,
        _mock_cleaner,
        _mock_categorizer,
        _mock_classifier,
    ):
        """When Pipeline is constructed with cascade_classifier, CascadeCategorizerNode
        should be initialized with cascade=some_cascade."""
        from modules.processing.pipeline.graph import Pipeline

        mock_cascade = MagicMock(name="CascadeClassifier")
        mock_llm = MagicMock()
        mock_budget = MagicMock()
        mock_prompt_loader = MagicMock()
        mock_event_bus = MagicMock()

        Pipeline(
            deps=PipelineDeps(
                llm=mock_llm,
                budget=mock_budget,
                prompt_loader=mock_prompt_loader,
                event_bus=mock_event_bus,
                analyzers=PipelineAnalyzers(cascade_classifier=mock_cascade),
            ),
        )

        _mock_categorizer.assert_called_once_with(
            mock_llm, mock_prompt_loader, cascade=mock_cascade
        )


class TestEntityExtractorNodeReceivesGliner:
    """EntityExtractorNode should receive the gliner_extractor parameter from Pipeline."""

    @patch("modules.processing.pipeline.graph.CascadeClassifierNode")
    @patch("modules.processing.pipeline.graph.CascadeCategorizerNode")
    @patch("modules.processing.pipeline.graph.CleanerNode")
    @patch("modules.processing.pipeline.graph.VectorizeNode")
    @patch("modules.processing.pipeline.graph.BatchMergerNode")
    @patch("modules.processing.pipeline.graph.ReVectorizeNode")
    @patch("modules.processing.pipeline.graph.AnalyzeNode")
    @patch("modules.processing.pipeline.graph.RuleBasedQualityScorerNode")
    @patch("modules.processing.pipeline.graph.RuleBasedCredibilityCheckerNode")
    @patch("modules.processing.pipeline.graph.EntityExtractorNode")
    @patch("modules.processing.pipeline.graph.ConflictDetectorNode")
    @patch("modules.processing.pipeline.graph.CheckpointCleanupNode")
    def test_gliner_passed_to_entity_extractor_node(
        self,
        _mock_checkpoint,
        _mock_conflict,
        _mock_entity,
        _mock_credibility,
        _mock_quality,
        _mock_analyze,
        _mock_re_vectorize,
        _mock_batch_merger,
        _mock_vectorize,
        _mock_cleaner,
        _mock_categorizer,
        _mock_classifier,
    ):
        """When Pipeline is constructed with gliner_extractor, EntityExtractorNode
        should receive it as gliner_extractor=some_gliner."""
        from modules.processing.pipeline.graph import Pipeline

        mock_gliner = MagicMock(name="GLiNERExtractor")
        mock_llm = MagicMock()
        mock_budget = MagicMock()
        mock_prompt_loader = MagicMock()
        mock_event_bus = MagicMock()

        Pipeline(
            deps=PipelineDeps(
                llm=mock_llm,
                budget=mock_budget,
                prompt_loader=mock_prompt_loader,
                event_bus=mock_event_bus,
                nlp=PipelineNlpTools(gliner_extractor=mock_gliner),
            ),
        )

        _mock_entity.assert_called_once()
        call_kwargs = _mock_entity.call_args[1]
        assert call_kwargs["gliner_extractor"] is mock_gliner


class TestAnalyzeNodeReceivesMcSampler:
    """AnalyzeNode should receive the mc_sampler parameter from Pipeline."""

    @patch("modules.processing.pipeline.graph.CascadeClassifierNode")
    @patch("modules.processing.pipeline.graph.CascadeCategorizerNode")
    @patch("modules.processing.pipeline.graph.CleanerNode")
    @patch("modules.processing.pipeline.graph.VectorizeNode")
    @patch("modules.processing.pipeline.graph.BatchMergerNode")
    @patch("modules.processing.pipeline.graph.ReVectorizeNode")
    @patch("modules.processing.pipeline.graph.AnalyzeNode")
    @patch("modules.processing.pipeline.graph.RuleBasedQualityScorerNode")
    @patch("modules.processing.pipeline.graph.RuleBasedCredibilityCheckerNode")
    @patch("modules.processing.pipeline.graph.EntityExtractorNode")
    @patch("modules.processing.pipeline.graph.ConflictDetectorNode")
    @patch("modules.processing.pipeline.graph.CheckpointCleanupNode")
    def test_mc_sampler_passed_to_analyze_node(
        self,
        _mock_checkpoint,
        _mock_conflict,
        _mock_entity,
        _mock_credibility,
        _mock_quality,
        _mock_analyze,
        _mock_re_vectorize,
        _mock_batch_merger,
        _mock_vectorize,
        _mock_cleaner,
        _mock_categorizer,
        _mock_classifier,
    ):
        """When Pipeline is constructed with mc_sampler, AnalyzeNode
        should receive it as mc_sampler=some_sampler."""
        from modules.processing.pipeline.graph import Pipeline

        mock_sampler = MagicMock(name="MCSampler")
        mock_llm = MagicMock()
        mock_budget = MagicMock()
        mock_prompt_loader = MagicMock()
        mock_event_bus = MagicMock()

        Pipeline(
            deps=PipelineDeps(
                llm=mock_llm,
                budget=mock_budget,
                prompt_loader=mock_prompt_loader,
                event_bus=mock_event_bus,
                analyzers=PipelineAnalyzers(mc_sampler=mock_sampler),
            ),
        )

        _mock_analyze.assert_called_once()
        call_kwargs = _mock_analyze.call_args[1]
        assert call_kwargs["mc_sampler"] is mock_sampler


class TestPipelineNoMlComponentsDefaultsToNone:
    """When Pipeline is constructed without ML components, nodes should get None."""

    @patch("modules.processing.pipeline.graph.CascadeClassifierNode")
    @patch("modules.processing.pipeline.graph.CascadeCategorizerNode")
    @patch("modules.processing.pipeline.graph.CleanerNode")
    @patch("modules.processing.pipeline.graph.VectorizeNode")
    @patch("modules.processing.pipeline.graph.BatchMergerNode")
    @patch("modules.processing.pipeline.graph.ReVectorizeNode")
    @patch("modules.processing.pipeline.graph.AnalyzeNode")
    @patch("modules.processing.pipeline.graph.RuleBasedQualityScorerNode")
    @patch("modules.processing.pipeline.graph.RuleBasedCredibilityCheckerNode")
    @patch("modules.processing.pipeline.graph.EntityExtractorNode")
    @patch("modules.processing.pipeline.graph.ConflictDetectorNode")
    @patch("modules.processing.pipeline.graph.CheckpointCleanupNode")
    def test_no_cascade_defaults_to_none(
        self,
        _mock_checkpoint,
        _mock_conflict,
        _mock_entity,
        _mock_credibility,
        _mock_quality,
        _mock_analyze,
        _mock_re_vectorize,
        _mock_batch_merger,
        _mock_vectorize,
        _mock_cleaner,
        _mock_categorizer,
        _mock_classifier,
    ):
        """When cascade_classifier is not provided, CascadeClassifierNode gets cascade=None."""
        from modules.processing.pipeline.graph import Pipeline

        mock_llm = MagicMock()
        mock_budget = MagicMock()
        mock_prompt_loader = MagicMock()
        mock_event_bus = MagicMock()

        Pipeline(
            deps=PipelineDeps(
                llm=mock_llm,
                budget=mock_budget,
                prompt_loader=mock_prompt_loader,
                event_bus=mock_event_bus,
            ),
        )

        _mock_classifier.assert_called_once_with(
            mock_llm, mock_budget, mock_prompt_loader, cascade=None
        )

    @patch("modules.processing.pipeline.graph.CascadeClassifierNode")
    @patch("modules.processing.pipeline.graph.CascadeCategorizerNode")
    @patch("modules.processing.pipeline.graph.CleanerNode")
    @patch("modules.processing.pipeline.graph.VectorizeNode")
    @patch("modules.processing.pipeline.graph.BatchMergerNode")
    @patch("modules.processing.pipeline.graph.ReVectorizeNode")
    @patch("modules.processing.pipeline.graph.AnalyzeNode")
    @patch("modules.processing.pipeline.graph.RuleBasedQualityScorerNode")
    @patch("modules.processing.pipeline.graph.RuleBasedCredibilityCheckerNode")
    @patch("modules.processing.pipeline.graph.EntityExtractorNode")
    @patch("modules.processing.pipeline.graph.ConflictDetectorNode")
    @patch("modules.processing.pipeline.graph.CheckpointCleanupNode")
    def test_no_gliner_defaults_to_none(
        self,
        _mock_checkpoint,
        _mock_conflict,
        _mock_entity,
        _mock_credibility,
        _mock_quality,
        _mock_analyze,
        _mock_re_vectorize,
        _mock_batch_merger,
        _mock_vectorize,
        _mock_cleaner,
        _mock_categorizer,
        _mock_classifier,
    ):
        """When gliner_extractor is not provided, EntityExtractorNode gets gliner_extractor=None."""
        from modules.processing.pipeline.graph import Pipeline

        mock_llm = MagicMock()
        mock_budget = MagicMock()
        mock_prompt_loader = MagicMock()
        mock_event_bus = MagicMock()

        Pipeline(
            deps=PipelineDeps(
                llm=mock_llm,
                budget=mock_budget,
                prompt_loader=mock_prompt_loader,
                event_bus=mock_event_bus,
            ),
        )

        _mock_entity.assert_called_once()
        call_kwargs = _mock_entity.call_args[1]
        assert call_kwargs["gliner_extractor"] is None

    @patch("modules.processing.pipeline.graph.CascadeClassifierNode")
    @patch("modules.processing.pipeline.graph.CascadeCategorizerNode")
    @patch("modules.processing.pipeline.graph.CleanerNode")
    @patch("modules.processing.pipeline.graph.VectorizeNode")
    @patch("modules.processing.pipeline.graph.BatchMergerNode")
    @patch("modules.processing.pipeline.graph.ReVectorizeNode")
    @patch("modules.processing.pipeline.graph.AnalyzeNode")
    @patch("modules.processing.pipeline.graph.RuleBasedQualityScorerNode")
    @patch("modules.processing.pipeline.graph.RuleBasedCredibilityCheckerNode")
    @patch("modules.processing.pipeline.graph.EntityExtractorNode")
    @patch("modules.processing.pipeline.graph.ConflictDetectorNode")
    @patch("modules.processing.pipeline.graph.CheckpointCleanupNode")
    def test_no_mc_sampler_defaults_to_none(
        self,
        _mock_checkpoint,
        _mock_conflict,
        _mock_entity,
        _mock_credibility,
        _mock_quality,
        _mock_analyze,
        _mock_re_vectorize,
        _mock_batch_merger,
        _mock_vectorize,
        _mock_cleaner,
        _mock_categorizer,
        _mock_classifier,
    ):
        """When mc_sampler is not provided, AnalyzeNode gets mc_sampler=None."""
        from modules.processing.pipeline.graph import Pipeline

        mock_llm = MagicMock()
        mock_budget = MagicMock()
        mock_prompt_loader = MagicMock()
        mock_event_bus = MagicMock()

        Pipeline(
            deps=PipelineDeps(
                llm=mock_llm,
                budget=mock_budget,
                prompt_loader=mock_prompt_loader,
                event_bus=mock_event_bus,
            ),
        )

        _mock_analyze.assert_called_once()
        call_kwargs = _mock_analyze.call_args[1]
        assert call_kwargs["mc_sampler"] is None


# ---------------------------------------------------------------------------
# Task 3.2 — Container ML component initialization tests
# ---------------------------------------------------------------------------


class TestContainerInitMlComponents:
    """Container.init_ml_components() should gracefully degrade on failure."""

    def test_has_init_ml_components_method(self):
        """Container should have an init_ml_components method."""
        from src.container import Container

        assert hasattr(
            Container, "init_ml_components"
        ), "Container must have init_ml_components() method"
        assert callable(Container.init_ml_components)

    @pytest.mark.asyncio
    async def test_cascade_classifier_none_on_import_failure(self):
        """When CascadeClassifier import fails, cascade_classifier should be set to None
        and a WARNING should be logged."""
        from src.container import Container

        container = Container()
        mock_settings = MagicMock()
        container._settings = mock_settings
        container._llm_client = MagicMock()

        mock_log = MagicMock()

        with (
            patch("core.observability.get_logger", return_value=mock_log),
            patch(
                "modules.processing.nodes.classification.cascade_classifier.CascadeClassifier",
                side_effect=ImportError("No module named 'fasttext'"),
            ),
        ):
            result = await container.init_ml_components()

        assert container._cascade_classifier is None
        assert result["cascade_classifier"] is False
        # Verify WARNING was logged about cascade failure
        warning_calls = mock_log.warning.call_args_list
        cascade_warnings = [c for c in warning_calls if "cascade" in str(c).lower()]
        assert len(cascade_warnings) > 0, "Expected a WARNING log about cascade classifier failure"

    @pytest.mark.asyncio
    async def test_gliner_extractor_none_on_import_failure(self):
        """When GLiNER import fails, gliner_extractor should be set to None
        and a WARNING should be logged."""
        from src.container import Container

        container = Container()
        mock_settings = MagicMock()
        container._settings = mock_settings
        container._llm_client = MagicMock()

        mock_log = MagicMock()

        with (
            patch("core.observability.get_logger", return_value=mock_log),
            patch(
                "modules.processing.nodes.extraction.gliner_extractor.GLiNERExtractor",
                side_effect=ImportError("No module named 'gliner'"),
            ),
        ):
            result = await container.init_ml_components()

        assert container._gliner_extractor is None
        assert result["gliner_extractor"] is False
        # Verify WARNING was logged about GLiNER failure
        warning_calls = mock_log.warning.call_args_list
        gliner_warnings = [c for c in warning_calls if "gliner" in str(c).lower()]
        assert len(gliner_warnings) > 0, "Expected a WARNING log about GLiNER failure"

    @pytest.mark.asyncio
    async def test_all_ml_components_initialized_on_success(self):
        """When all ML model loads succeed, components should be initialized."""
        from src.container import Container

        container = Container()
        mock_settings = MagicMock()
        container._settings = mock_settings
        container._llm_client = MagicMock()

        mock_log = MagicMock()
        mock_cascade = MagicMock()
        mock_gliner = MagicMock()

        with (
            patch("core.observability.get_logger", return_value=mock_log),
            patch(
                "modules.processing.nodes.classification.cascade_classifier.CascadeClassifier",
                return_value=mock_cascade,
            ),
            patch(
                "modules.processing.nodes.extraction.gliner_extractor.GLiNERExtractor",
                return_value=mock_gliner,
            ),
            patch.object(container, "init_mc_sampler", new_callable=AsyncMock),
        ):
            result = await container.init_ml_components()

        assert container._cascade_classifier is mock_cascade
        assert container._gliner_extractor is mock_gliner
        assert result["cascade_classifier"] is True
        assert result["gliner_extractor"] is True

    @pytest.mark.asyncio
    async def test_partial_failure_cascade_only(self):
        """When only cascade fails, gliner_extractor should still be initialized."""
        from src.container import Container

        container = Container()
        mock_settings = MagicMock()
        container._settings = mock_settings
        container._llm_client = MagicMock()

        mock_log = MagicMock()
        mock_gliner = MagicMock()

        with (
            patch("core.observability.get_logger", return_value=mock_log),
            patch(
                "modules.processing.nodes.classification.cascade_classifier.CascadeClassifier",
                side_effect=ImportError("No module named 'fasttext'"),
            ),
            patch(
                "modules.processing.nodes.extraction.gliner_extractor.GLiNERExtractor",
                return_value=mock_gliner,
            ),
            patch.object(container, "init_mc_sampler", new_callable=AsyncMock),
        ):
            result = await container.init_ml_components()

        assert container._cascade_classifier is None
        assert container._gliner_extractor is mock_gliner
        assert result["cascade_classifier"] is False
        assert result["gliner_extractor"] is True

    @pytest.mark.asyncio
    async def test_partial_failure_gliner_only(self):
        """When only GLiNER fails, cascade_classifier should still be initialized."""
        from src.container import Container

        container = Container()
        mock_settings = MagicMock()
        container._settings = mock_settings
        container._llm_client = MagicMock()

        mock_log = MagicMock()
        mock_cascade = MagicMock()

        with (
            patch("core.observability.get_logger", return_value=mock_log),
            patch(
                "modules.processing.nodes.classification.cascade_classifier.CascadeClassifier",
                return_value=mock_cascade,
            ),
            patch(
                "modules.processing.nodes.extraction.gliner_extractor.GLiNERExtractor",
                side_effect=ImportError("No module named 'gliner'"),
            ),
            patch.object(container, "init_mc_sampler", new_callable=AsyncMock),
        ):
            result = await container.init_ml_components()

        assert container._cascade_classifier is mock_cascade
        assert container._gliner_extractor is None
        assert result["cascade_classifier"] is True
        assert result["gliner_extractor"] is False

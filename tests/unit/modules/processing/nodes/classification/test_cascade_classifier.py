"""Tests for CascadeClassifier — 4-layer cascade: fastText → SetFit → fusion → LLM."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.classification.cascade_classifier import CascadeClassifier
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    return RawArticle(
        url="https://example.com/article",
        title="Test Article",
        body="Some body content",
        source="test",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


# ── Layer 1: fastText ──────────────────────────────────────────────


class TestFastTextLayer:
    """fastText layer: high confidence returns directly."""

    def test_fasttext_high_confidence_returns_directly(self):
        """When fastText returns conf >= 0.9, return directly without calling SetFit."""
        mock_ft = MagicMock()
        mock_ft.predict.return_value = (("__label__news",), (0.95,))

        clf = CascadeClassifier()
        clf._ft_model = mock_ft

        result = clf.classify("重大新闻发布")

        assert result is not None
        label, confidence = result
        assert label == "news"
        assert confidence >= 0.9
        # SetFit should NOT be loaded or called
        assert clf._sf_model is None

    def test_fasttext_low_confidence_falls_to_setfit(self):
        """When fastText returns conf < 0.9, SetFit should be called."""
        mock_ft = MagicMock()
        mock_ft.predict.return_value = (("__label__news",), (0.5,))

        mock_sf = MagicMock()
        import torch

        mock_sf.predict_proba.return_value = torch.tensor([[0.1, 0.9]])
        mock_sf.labels = ["non_news", "news"]

        clf = CascadeClassifier()
        clf._ft_model = mock_ft
        clf._sf_model = mock_sf

        result = clf.classify("模糊标题")

        # SetFit should have been called
        mock_sf.predict_proba.assert_called_once()
        assert result is not None


# ── Layer 2: SetFit ────────────────────────────────────────────────


class TestSetFitLayer:
    """SetFit layer: high confidence returns directly."""

    def test_setfit_high_confidence_returns_directly(self):
        """When SetFit returns conf >= 0.8, return directly without fusion."""
        mock_ft = MagicMock()
        mock_ft.predict.return_value = (("__label__news",), (0.5,))

        mock_sf = MagicMock()
        import torch

        mock_sf.predict_proba.return_value = torch.tensor([[0.05, 0.92]])
        mock_sf.labels = ["non_news", "news"]

        clf = CascadeClassifier()
        clf._ft_model = mock_ft
        clf._sf_model = mock_sf

        result = clf.classify("模糊标题")

        assert result is not None
        label, confidence = result
        assert label == "news"
        assert confidence >= 0.8

    def test_setfit_moderate_confidence_tries_fusion(self):
        """When SetFit returns moderate conf, fusion layer is attempted."""
        mock_ft = MagicMock()
        mock_ft.predict.return_value = (("__label__news",), (0.7,))

        mock_sf = MagicMock()
        import torch

        # SetFit confidence = 0.75 (< 0.8 threshold)
        mock_sf.predict_proba.return_value = torch.tensor([[0.25, 0.75]])
        mock_sf.labels = ["non_news", "news"]

        clf = CascadeClassifier()
        clf._ft_model = mock_ft
        clf._sf_model = mock_sf

        result = clf.classify("模糊标题")

        # Fusion: 0.6 * 0.7 + 0.4 * 0.75 = 0.42 + 0.30 = 0.72 < 0.8
        # Should fall through to None
        assert result is None


# ── Layer 3: Fusion ────────────────────────────────────────────────


class TestFusionLayer:
    """Fusion layer: combined confidence from fastText + SetFit."""

    def test_fused_confidence_above_threshold(self):
        """Both models return moderate confidence, fusion >= 0.8."""
        mock_ft = MagicMock()
        mock_ft.predict.return_value = (("__label__news",), (0.85,))

        mock_sf = MagicMock()
        import torch

        # SetFit confidence = 0.78 (< 0.8 threshold, so falls to fusion)
        mock_sf.predict_proba.return_value = torch.tensor([[0.22, 0.78]])
        mock_sf.labels = ["non_news", "news"]

        clf = CascadeClassifier()
        clf._ft_model = mock_ft
        clf._sf_model = mock_sf

        result = clf.classify("模糊标题")

        # Fusion: 0.6 * 0.85 + 0.4 * 0.78 = 0.51 + 0.312 = 0.822 >= 0.8
        assert result is not None
        label, confidence = result
        assert label == "news"
        assert confidence >= 0.8

    def test_fused_confidence_below_threshold_falls_to_llm(self):
        """Both models return low confidence, fusion < 0.8, falls through to LLM."""
        mock_ft = MagicMock()
        mock_ft.predict.return_value = (("__label__news",), (0.4,))

        mock_sf = MagicMock()
        import torch

        # SetFit confidence = 0.5 (< 0.8 threshold)
        mock_sf.predict_proba.return_value = torch.tensor([[0.5, 0.5]])
        mock_sf.labels = ["non_news", "news"]

        clf = CascadeClassifier()
        clf._ft_model = mock_ft
        clf._sf_model = mock_sf

        result = clf.classify("非常模糊的标题")

        # Fusion: 0.6 * 0.4 + 0.4 * 0.5 = 0.24 + 0.20 = 0.44 < 0.8
        assert result is None


# ── Return type ─────────────────────────────────────────────────────


class TestReturnType:
    """Verify classify returns (label: str, confidence: float)."""

    def test_classify_returns_label_and_confidence(self):
        """classify() returns tuple of (label: str, confidence: float)."""
        mock_ft = MagicMock()
        mock_ft.predict.return_value = (("__label__news",), (0.93,))

        clf = CascadeClassifier()
        clf._ft_model = mock_ft

        result = clf.classify("重大新闻")

        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], float)


# ── Model loading ───────────────────────────────────────────────────


class TestModelLoading:
    """Verify models are loaded from configured paths."""

    @patch("modules.processing.nodes.classification.cascade_classifier.fasttext")
    def test_fasttext_model_loading(self, mock_fasttext):
        """fastText model is loaded from configured path."""
        mock_fasttext.load_model.return_value = MagicMock()

        clf = CascadeClassifier(fasttext_model_path="/models/ft.bin")
        clf.load_models()

        mock_fasttext.load_model.assert_called_once_with("/models/ft.bin")
        assert clf._ft_model is not None

    @patch("modules.processing.nodes.classification.cascade_classifier.SetFitModel")
    def test_setfit_model_loading(self, mock_setfit_cls):
        """SetFit model is loaded from configured path."""
        mock_setfit_cls.from_pretrained.return_value = MagicMock()

        clf = CascadeClassifier(setfit_model_path="/models/sf")
        clf.load_models()

        mock_setfit_cls.from_pretrained.assert_called_once_with("/models/sf")
        assert clf._sf_model is not None

    def test_no_models_available_falls_to_rules(self):
        """If no fasttext/setfit models loaded, classify returns None (falls to rules)."""
        clf = CascadeClassifier()
        # No models loaded
        result = clf.classify("任何标题")

        # Should return None, meaning fall through to rule-based or LLM
        assert result is None


# ── Integration with CascadeClassifierNode ──────────────────────────


class TestCascadeIntegration:
    """CascadeClassifier integrates with CascadeClassifierNode."""

    @pytest.mark.asyncio
    async def test_rules_still_used_as_pre_filter(self, sample_raw):
        """Rule classification still runs first before ML models."""
        from modules.processing.nodes.classification.classifier import CascadeClassifierNode

        # Title with 2+ news keywords — rules should catch it
        sample_raw.title = "据报道 国家发布重要公告"
        state = PipelineState(raw=sample_raw)

        node = CascadeClassifierNode()
        result = await node.execute(state)

        # Rules matched, no need for ML or LLM
        assert result["is_news"] is True

    @pytest.mark.asyncio
    async def test_cascade_between_rules_and_llm(self, sample_raw):
        """When rules return None, cascade is tried before LLM."""
        from modules.processing.nodes.classification.classifier import CascadeClassifierNode

        # Ambiguous title — rules return None
        sample_raw.title = "Ambiguous Title"
        state = PipelineState(raw=sample_raw)

        mock_cascade = MagicMock()
        mock_cascade.classify.return_value = ("news", 0.92)

        node = CascadeClassifierNode(cascade=mock_cascade)
        result = await node.execute(state)

        mock_cascade.classify.assert_called_once_with("Ambiguous Title")
        assert result["is_news"] is True

    @pytest.mark.asyncio
    async def test_cascade_returns_none_falls_to_llm(self, sample_raw):
        """When cascade returns None, LLM fallback is used."""
        from core.llm.validation.output_validator import ClassifierOutput
        from modules.processing.nodes.classification.classifier import CascadeClassifierNode

        sample_raw.title = "Ambiguous Title"
        state = PipelineState(raw=sample_raw)

        mock_cascade = MagicMock()
        mock_cascade.classify.return_value = None

        mock_llm = AsyncMock()
        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=True, confidence=0.7))
        mock_budget = MagicMock()
        mock_budget.truncate = MagicMock(return_value="body")
        mock_prompt_loader = MagicMock()
        mock_prompt_loader.get_version = MagicMock(return_value="1.0.0")

        node = CascadeClassifierNode(
            cascade=mock_cascade,
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )
        result = await node.execute(state)

        mock_cascade.classify.assert_called_once()
        mock_llm.call_at.assert_called_once()
        assert result["is_news"] is True

    @pytest.mark.asyncio
    async def test_cascade_non_news_label(self, sample_raw):
        """When cascade returns a non-news label, is_news is False."""
        from modules.processing.nodes.classification.classifier import CascadeClassifierNode

        sample_raw.title = "Ambiguous Title"
        state = PipelineState(raw=sample_raw)

        mock_cascade = MagicMock()
        mock_cascade.classify.return_value = ("non_news", 0.88)

        node = CascadeClassifierNode(cascade=mock_cascade)
        result = await node.execute(state)

        assert result["is_news"] is False
        assert result["terminal"] is True

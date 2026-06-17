# Copyright (c) 2026 KirkyX. All Rights Reserved
"""CascadeClassifier — 4-layer cascade: fastText → SetFit → fusion → LLM."""

from __future__ import annotations

import fasttext

from core.observability import get_logger

log = get_logger(__name__)


class CascadeClassifier:
    """4-layer cascade classifier: fastText → SetFit → fusion → LLM.

    No matching Protocol yet — standalone classifier component.
    """

    FASTTEXT_THRESHOLD = 0.9
    SETFIT_THRESHOLD = 0.8
    FUSION_THRESHOLD = 0.8
    FUSION_WEIGHTS = (0.6, 0.4)  # fasttext, setfit

    def __init__(
        self,
        fasttext_model_path: str | None = None,
        setfit_model_path: str | None = None,
    ) -> None:
        self._ft_model = None
        self._sf_model = None
        self._ft_path = fasttext_model_path
        self._sf_path = setfit_model_path

    def load_models(self) -> None:
        """Load fasttext and setfit models from configured paths."""
        if self._ft_path:
            self._ft_model = fasttext.load_model(self._ft_path)
            log.info("fasttext_model_loaded", path=self._ft_path)
        if self._sf_path:
            from setfit import SetFitModel

            self._sf_model = SetFitModel.from_pretrained(self._sf_path)
            log.info("setfit_model_loaded", path=self._sf_path)

    def classify(self, text: str) -> tuple[str, float] | None:
        """Classify text through the cascade. Returns (label, confidence) or None."""
        # Layer 1: fastText
        if self._ft_model:
            labels, probs = self._ft_model.predict(text, k=1)
            ft_label = labels[0].replace("__label__", "")
            ft_conf = float(probs[0])
            if ft_conf >= self.FASTTEXT_THRESHOLD:
                log.debug("cascade_fasttext_hit", label=ft_label, confidence=ft_conf)
                return (ft_label, ft_conf)

            # Layer 2: SetFit
            if self._sf_model:
                sf_probs = self._sf_model.predict_proba([text])
                sf_conf = float(max(sf_probs[0]))
                sf_label_idx = int(sf_probs[0].argmax())
                if sf_conf >= self.SETFIT_THRESHOLD:
                    label = self._get_setfit_label(sf_label_idx)
                    log.debug("cascade_setfit_hit", label=label, confidence=sf_conf)
                    return (label, sf_conf)

                # Layer 3: Fusion
                fused_conf = self.FUSION_WEIGHTS[0] * ft_conf + self.FUSION_WEIGHTS[1] * sf_conf
                if fused_conf >= self.FUSION_THRESHOLD:
                    log.debug("cascade_fusion_hit", label=ft_label, confidence=fused_conf)
                    return (ft_label, fused_conf)

        # Fall through to LLM
        return None

    def _get_setfit_label(self, idx: int) -> str:
        """Map setfit class index to label."""
        if hasattr(self._sf_model, "labels") and self._sf_model.labels:
            return self._sf_model.labels[idx]
        return str(idx)

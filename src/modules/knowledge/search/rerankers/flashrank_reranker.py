# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Flashrank reranker for cross-encoder re-ranking.

Flashrank uses lightweight ONNX models for fast CPU-based re-ranking,
providing significant quality improvements over vector similarity alone.

Features:
- Ultra-lightweight ONNX models (~4-50MB)
- CPU-only inference (no GPU required)
- Graceful degradation when model unavailable
- Multi-language support
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from core.observability.logging import get_logger

log = get_logger("flashrank_reranker")


@dataclass
class RerankResult:
    """Result from re-ranking."""

    doc_id: str
    score: float
    title: str
    content: str
    original_rank: int
    new_rank: int
    metadata: dict[str, Any] = field(default_factory=dict)


class FlashrankReranker:
    """Flashrank-based cross-encoder reranker.

    Uses pre-trained ONNX models for fast CPU re-ranking without GPU.
    Supports graceful degradation when models are unavailable.

    Args:
        model_name: Model name (tiny, small, medium, multilingual).
        cache_dir: Directory for model caching.
        enabled: Whether reranking is enabled.
    """

    # Available models with their sizes
    MODELS = {
        "tiny": "flashrank-Tiny",
        "small": "flashrank-Small",
        "medium": "flashrank-Medium",
        "multilingual": "ms-marco-MultiBERT",
    }

    def __init__(
        self,
        model_name: str = "tiny",
        cache_dir: str | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize Flashrank reranker.

        Args:
            model_name: Model variant to use.
            cache_dir: Directory for model cache.
            enabled: Whether reranking is enabled.
        """
        self._model_name = model_name
        self._cache_dir = cache_dir or os.environ.get(
            "FLASHRANK_CACHE_DIR",
            os.path.expanduser("~/.cache/flashrank"),
        )
        self._enabled = enabled
        self._ranker: Any = None
        self._available = False

        if self._enabled:
            self._initialize_ranker()

    def _initialize_ranker(self) -> None:
        """Initialize the Flashrank ranker model."""
        try:
            from flashrank import Ranker  # type: ignore[import-untyped]

            model_path = self.MODELS.get(self._model_name, self.MODELS["tiny"])

            self._ranker = Ranker(
                model_name=model_path,
                cache_dir=self._cache_dir,
            )
            self._available = True

            log.info(
                "flashrank_initialized",
                model=self._model_name,
                model_path=model_path,
                cache_dir=self._cache_dir,
            )

        except ImportError:
            log.warning("flashrank_not_installed", fallback="pass_through")
            self._available = False

        except Exception as exc:
            log.warning(
                "flashrank_init_failed",
                error=str(exc),
                fallback="pass_through",
            )
            self._available = False

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Re-rank candidates using cross-encoder scoring.

        Args:
            query: Search query.
            candidates: List of candidate documents with 'content' or 'text' field.
            top_k: Number of top results to return. Returns all if None.

        Returns:
            Re-ranked candidates sorted by relevance score.
        """
        if not self._available or not candidates:
            return candidates[:top_k] if top_k else candidates

        try:
            from flashrank import RerankRequest

            # Prepare passages for flashrank
            passages = []
            for i, cand in enumerate(candidates):
                text = cand.get("content") or cand.get("text") or cand.get("title", "")
                passages.append(
                    {
                        "id": cand.get("id", str(i)),
                        "text": text,
                        **{k: v for k, v in cand.items() if k not in ("id", "text", "content")},
                    }
                )

            # Create rerank request
            rerank_request = RerankRequest(
                query=query,
                passages=passages,
            )

            # Get ranked results
            ranked = self._ranker.rerank(rerank_request)

            # Build output with new scores
            results = []
            for i, item in enumerate(ranked[:top_k] if top_k else ranked):
                result = {
                    "id": item.get("id", str(i)),
                    "text": item.get("text", ""),
                    "rerank_score": item.get("score", 0.0),
                    "original_rank": i,
                    "new_rank": i,
                }
                # Copy other fields
                for k, v in item.items():
                    if k not in result:
                        result[k] = v
                results.append(result)

            log.debug(
                "flashrank_rerank_complete",
                query=query[:50],
                candidates=len(candidates),
                returned=len(results),
            )

            return results

        except Exception as exc:
            log.error("flashrank_rerank_failed", error=str(exc), fallback="pass_through")
            return candidates[:top_k] if top_k else candidates

    def rerank_with_metadata(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        """Re-rank and return structured results with metadata.

        Args:
            query: Search query.
            candidates: List of candidate documents.
            top_k: Number of results to return.

        Returns:
            List of RerankResult objects.
        """
        if not self._available or not candidates:
            results = []
            for i, cand in enumerate(candidates[:top_k] if top_k else candidates):
                results.append(
                    RerankResult(
                        doc_id=cand.get("id", str(i)),
                        score=cand.get("score", 0.0),
                        title=cand.get("title", ""),
                        content=cand.get("content", "")[:500],
                        original_rank=i,
                        new_rank=i,
                        metadata=cand,
                    )
                )
            return results

        ranked = self.rerank(query, candidates, top_k)

        return [
            RerankResult(
                doc_id=item.get("id", str(i)),
                score=item.get("rerank_score", 0.0),
                title=item.get("title", ""),
                content=item.get("text", "")[:500],
                original_rank=item.get("original_rank", i),
                new_rank=i,
                metadata=item,
            )
            for i, item in enumerate(ranked)
        ]

    def is_available(self) -> bool:
        """Check if reranker is available."""
        return self._available

    def get_model_info(self) -> dict[str, Any]:
        """Get model information."""
        return {
            "model_name": self._model_name,
            "model_path": self.MODELS.get(self._model_name, "unknown"),
            "available": self._available,
            "cache_dir": self._cache_dir,
            "enabled": self._enabled,
        }

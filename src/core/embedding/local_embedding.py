# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Local embedding service using SentenceTransformer models.

Implements lazy-loaded embedding computation with background model loading.
Based on Sirchmunk's EmbeddingUtil design pattern.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import os
import threading
import warnings
from typing import Any

from core.observability.logging import get_logger

log = get_logger(__name__)


class LocalEmbeddingService:
    """Local embedding service using SentenceTransformer models (lazy-loaded).

    Implements: EmbeddingServiceProtocol

    Construction is cheap: __init__ only stores configuration.
    Call start_loading() to kick off the background model download +
    construction, and is_ready() to check completion. embed() will call
    start_loading() automatically if it hasn't been called.

    Example:
        service = LocalEmbeddingService(cache_dir="data/.cache/models")
        service.start_loading()  # Start background loading
        # ... do other initialization ...
        if service.is_ready():
            embedding = await service.embed("sample text")
    """

    DEFAULT_MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_DIM = 384

    def __init__(
        self,
        model_id: str | None = None,
        device: str | None = None,
        cache_dir: str | None = None,
    ) -> None:
        """Initialize the embedding service.

        Args:
            model_id: Model ID to use. Defaults to multilingual MiniLM.
            device: Device to use (cuda/cpu). Auto-detects if None.
            cache_dir: Directory to cache model weights.
        """
        self.model_id = model_id or os.getenv(
            "EMBEDDING_MODEL_ID", self.DEFAULT_MODEL_ID
        )
        self._cache_dir = cache_dir or os.getenv("EMBEDDING_CACHE_DIR")
        if self._cache_dir:
            self._cache_dir = os.path.expanduser(self._cache_dir)
        self.model: Any = None

        # Defer torch import to the background thread to avoid blocking
        # the event loop with the heavy first-import cost.
        if device is not None:
            self.device = device
        else:
            try:
                import torch

                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                self.device = "cpu"

        self._model_future: concurrent.futures.Future = concurrent.futures.Future()
        self._loading_started = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lazy background loading
    # ------------------------------------------------------------------

    def start_loading(self) -> None:
        """Kick off the background model load (idempotent)."""
        with self._lock:
            if self._loading_started:
                return
            self._loading_started = True

        worker = threading.Thread(
            target=self._load_model_bg,
            args=(self.model_id, self._cache_dir),
            daemon=True,
        )
        worker.start()
        log.info("embedding_model_loading_started", model_id=self.model_id)

    def _load_model_bg(self, model_id: str, cache_dir: str | None) -> None:
        """Runs in a daemon thread: download, construct, and warm-up."""
        try:
            model_dir = self._download_model(model_id, cache_dir)

            from sentence_transformers import SentenceTransformer

            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*position_ids.*")
                warnings.filterwarnings("ignore", category=FutureWarning)
                model = SentenceTransformer(model_dir, device=self.device)

            model.encode(["warmup"], show_progress_bar=False)

            self.model = model
            self._model_future.set_result(model)
            log.info(
                "embedding_model_ready",
                model_id=model_id,
                device=self.device,
                dim=model.get_sentence_embedding_dimension(),
            )
        except Exception as e:
            self._model_future.set_exception(e)
            log.error("embedding_model_failed", error=str(e), model_id=model_id)

    @staticmethod
    def _download_model(model_id: str, cache_dir: str | None = None) -> str:
        """Download model weights from ModelScope (or HuggingFace fallback).

        Args:
            model_id: The model ID to download.
            cache_dir: Optional cache directory.

        Returns:
            Path to the downloaded model directory.
        """
        try:
            from modelscope import snapshot_download
        except ImportError:
            raise RuntimeError(
                "modelscope is required. Install with: pip install modelscope"
            ) from None

        ignore = [
            "openvino/*",
            "onnx/*",
            "pytorch_model.bin",
            "rust_model.ot",
            "tf_model.h5",
        ]

        # Step 1: offline-first — try loading from local cache
        try:
            model_dir = snapshot_download(
                model_id=model_id,
                cache_dir=cache_dir,
                local_files_only=True,
                ignore_patterns=ignore,
            )
            log.info("model_loaded_from_cache", path=model_dir, model_id=model_id)
            return model_dir
        except Exception:
            log.debug("offline_cache_miss_trying_download", model_id=model_id)

        # Step 2: fallback — online download
        try:
            model_dir = snapshot_download(
                model_id=model_id,
                cache_dir=cache_dir,
                local_files_only=False,
                ignore_patterns=ignore,
            )
            log.info("model_downloaded", path=model_dir, model_id=model_id)
            return model_dir
        except Exception as e:
            log.error("model_download_failed", model_id=model_id, error=str(e))
            raise RuntimeError(
                f"Model download failed. Please check network or model_id. Error: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Model readiness helpers
    # ------------------------------------------------------------------

    def is_ready(self, timeout: float = 5.0) -> bool:
        """Return True if the model is loaded and ready.

        Args:
            timeout: Max seconds to wait for model future.

        Returns:
            True if model is ready, False otherwise.
        """
        try:
            self._model_future.result(timeout=0)
            return self.model is not None
        except concurrent.futures.TimeoutError:
            return False
        except Exception:
            return False

    def _ensure_model(self) -> None:
        """Wait for model to be ready (blocking)."""
        if not self._loading_started:
            self.start_loading()
        self._model_future.result()

    async def _ensure_model_async(self) -> None:
        """Wait for model to be ready (async)."""
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._ensure_model)

    # ------------------------------------------------------------------
    # Embedding computation
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> list[float]:
        """Compute embedding for a single text (async-safe).

        Args:
            text: Text to embed.

        Returns:
            384-dimensional embedding vector.
        """
        if self.model is None:
            await self._ensure_model_async()
        return self._encode_sync([text])[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings for multiple texts (async-safe).

        Args:
            texts: List of texts to embed.

        Returns:
            List of 384-dimensional embedding vectors.
        """
        if self.model is None:
            await self._ensure_model_async()
        return self._encode_sync(texts)

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        """Synchronous encode (called from async methods).

        Args:
            texts: Texts to encode.

        Returns:
            List of embedding vectors.
        """
        if self.model is None:
            raise RuntimeError("Model not loaded")
        embeddings = self.model.encode(texts, show_progress_bar=False)
        return [e.tolist() for e in embeddings]

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @property
    def dimension(self) -> int:
        """Return the embedding dimension (384)."""
        return self.EMBEDDING_DIM

    @staticmethod
    def compute_text_hash(text: str) -> str:
        """Compute SHA256 hash of text for cache key.

        Args:
            text: Text to hash.

        Returns:
            First 16 characters of SHA256 hash.
        """
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def get_model_info(self) -> dict[str, Any]:
        """Get model information.

        Returns:
            Dict with model_id, device, dimension, ready status.
        """
        return {
            "model_id": self.model_id,
            "device": self.device,
            "dimension": self.dimension,
            "ready": self.model is not None,
        }


__all__ = [
    "LocalEmbeddingService",
]

# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Utility functions for model ID extraction and management."""

from __future__ import annotations

from core.constants import EmbeddingModel, LLMRole
from core.observability import get_logger

log = get_logger(__name__)


def extract_embedding_model_id(llm_settings: object) -> str:
    """Extract embedding model ID from LLM configuration.

    Extracts the model_id from defaults.embedding.primary.
    Format: "embedding.aiping.Qwen3-Embedding-0.6B" -> "Qwen3-Embedding-0.6B"

    The label format is "<type>.<provider>.<model_id>" where model_id may
    contain dots (e.g., Qwen3-Embedding-0.6B). We split on first 2 dots only.

    Args:
        llm_settings: LLM settings object with defaults attribute.

    Returns:
        The embedding model ID string.
    """
    try:
        embedding_config = llm_settings.defaults.get(LLMRole.EMBEDDING)
        if embedding_config and embedding_config.primary:
            # Split only on first 2 dots to preserve model_id with dots
            parts = embedding_config.primary.split(".", 2)
            if len(parts) >= 3:
                return parts[2]  # Return model_id (third part)
    except Exception:
        log.warning("Failed to extract embedding model ID, using default", exc_info=True)
        pass
    # Fallback to default model
    return EmbeddingModel.DEFAULT

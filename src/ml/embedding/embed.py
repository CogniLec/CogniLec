"""Embedding model loading and encoding."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def load_embedding_model(
    model_name: str = "Qwen/Qwen3-Embedding-0.6B", device: str = "cuda"
) -> Any:
    """Load a sentence-transformers embedding model.

    Args:
        model_name: HuggingFace model ID
        device: cuda or cpu

    Returns:
        SentenceTransformer instance
    """
    from sentence_transformers import SentenceTransformer

    log.info("Loading embedding model %s on %s", model_name, device)
    return SentenceTransformer(model_name, device=device)


def encode_texts(
    model: Any,
    texts: list[str],
    batch_size: int = 32,
    normalize: bool = True,
) -> Any:
    """Encode texts into embeddings.

    Args:
        model: SentenceTransformer instance
        texts: list of strings to embed
        batch_size: encoding batch size
        normalize: L2-normalize embeddings

    Returns:
        numpy array of shape (len(texts), dim)
    """
    import numpy as np

    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=normalize,
    )
    return np.array(embeddings)

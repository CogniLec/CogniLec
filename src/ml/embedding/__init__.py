# Embedding utilities for S06 bake-off and S25-S27 embedding service
from src.ml.embedding.backfill import backfill_version
from src.ml.embedding.client import EmbeddingClient
from src.ml.embedding.embed import encode_texts, load_embedding_model
from src.ml.embedding.versioning import (
    DimensionError,
    ModelVersionInfo,
    get_active_version,
    get_version,
    stamp_version,
)
from src.ml.embedding.windowing import WindowedUtterance, build_windows

__all__ = [
    "DimensionError",
    "EmbeddingClient",
    "ModelVersionInfo",
    "WindowedUtterance",
    "backfill_version",
    "build_windows",
    "encode_texts",
    "get_active_version",
    "get_version",
    "load_embedding_model",
    "stamp_version",
]

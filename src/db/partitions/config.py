"""Partition configuration constants."""

from __future__ import annotations

PARTITIONED_TABLES: list[str] = [
    "utterances",
    "segments",
    "note_sections",
    "note_provenance",
]

VECTOR_TABLES: frozenset[str] = frozenset({"utterances", "note_sections"})

HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64
HNSW_EF_SEARCH = 32
EMBEDDING_DIM = 1024
PROVISION_TIMEOUT_SECONDS = 2
MAX_PROVISION_RETRIES = 3

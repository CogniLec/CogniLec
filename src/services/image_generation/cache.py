"""S63 — concept cache keyed by (subject_id, SHA-256(normalized concept)). FR-4.11."""

from __future__ import annotations

import hashlib
import uuid


def normalize_concept(concept_description: str) -> str:
    return " ".join(concept_description.strip().lower().split())


def concept_hash(concept_description: str) -> str:
    return hashlib.sha256(normalize_concept(concept_description).encode("utf-8")).hexdigest()


class InMemoryConceptCache:
    """Process-local cache-aside store, mirroring `image_generation_cache`'s
    (subject_id, concept_hash) unique key. The DB-backed repository
    (`src/db/repositories/generation_cache_repo.py`) is the real persistence
    layer used by the API route; this is used directly by unit tests that
    don't need a database.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[uuid.UUID, str], uuid.UUID] = {}

    def get(self, subject_id: uuid.UUID, concept_description: str) -> uuid.UUID | None:
        return self._store.get((subject_id, concept_hash(concept_description)))

    def put(
        self, subject_id: uuid.UUID, concept_description: str, generated_image_id: uuid.UUID
    ) -> None:
        self._store[(subject_id, concept_hash(concept_description))] = generated_image_id

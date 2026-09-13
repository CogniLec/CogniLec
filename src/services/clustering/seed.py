"""S53 — centroid seeding: syllabus item embeddings seed session-1 clustering."""

from __future__ import annotations

import uuid
from enum import StrEnum

import numpy as np
from pydantic import BaseModel
from src.db.repositories.syllabus_repo import SyllabusRepository

TIGHT_CADENCE_SESSIONS = 5
SEED_REPLACEMENT_THRESHOLD = 0.70


class SeedingStatus(StrEnum):
    NOT_SEEDED = "not_seeded"
    SEEDED = "seeded"
    STABILIZED = "stabilized"


class CentroidSeed(BaseModel):
    syllabus_item_id: uuid.UUID
    title: str
    embedding: list[float]
    initial_topic_id: uuid.UUID | None = None
    replaced_by_data: bool = False


class SeedingResult(BaseModel):
    subject_id: uuid.UUID
    status: SeedingStatus
    seed_count: int
    seeds: list[CentroidSeed]
    session_count: int
    recluster_cadence: str


class CentroidSeedService:
    """Reads syllabus item embeddings and turns them into KMeans-ready seeds."""

    def __init__(self, syllabus_repo: SyllabusRepository) -> None:
        self._repo = syllabus_repo
        self._seeds_by_subject: dict[uuid.UUID, list[CentroidSeed]] = {}

    async def create_seeds(self, subject_id: uuid.UUID) -> SeedingResult:
        """Create initial centroid seeds from syllabus items (empty if none)."""
        items = await self._repo.list_for_subject(subject_id)
        embedded = [i for i in items if i.embedding is not None]

        if not embedded:
            return SeedingResult(
                subject_id=subject_id,
                status=SeedingStatus.NOT_SEEDED,
                seed_count=0,
                seeds=[],
                session_count=0,
                recluster_cadence="normal",
            )

        seeds = [
            CentroidSeed(syllabus_item_id=i.id, title=i.title, embedding=list(i.embedding))
            for i in embedded
        ]
        self._seeds_by_subject[subject_id] = seeds
        return SeedingResult(
            subject_id=subject_id,
            status=SeedingStatus.SEEDED,
            seed_count=len(seeds),
            seeds=seeds,
            session_count=0,
            recluster_cadence="tight",
        )

    async def get_seeds(self, subject_id: uuid.UUID) -> list[CentroidSeed]:
        return self._seeds_by_subject.get(subject_id, [])

    async def check_seed_status(
        self, subject_id: uuid.UUID, session_count: int = 0
    ) -> SeedingResult:
        seeds = self._seeds_by_subject.get(subject_id)
        if not seeds:
            return SeedingResult(
                subject_id=subject_id,
                status=SeedingStatus.NOT_SEEDED,
                seed_count=0,
                seeds=[],
                session_count=session_count,
                recluster_cadence="normal",
            )
        active = [s for s in seeds if not s.replaced_by_data]
        status = SeedingStatus.SEEDED if active else SeedingStatus.STABILIZED
        cadence = "tight" if session_count < TIGHT_CADENCE_SESSIONS and active else "normal"
        return SeedingResult(
            subject_id=subject_id,
            status=status,
            seed_count=len(active),
            seeds=seeds,
            session_count=session_count,
            recluster_cadence=cadence,
        )

    async def replace_seed(
        self, subject_id: uuid.UUID, seed_id: uuid.UUID, replacement_embedding: list[float]
    ) -> CentroidSeed | None:
        seeds = self._seeds_by_subject.get(subject_id, [])
        for i, seed in enumerate(seeds):
            if seed.syllabus_item_id == seed_id:
                updated = seed.model_copy(update={"replaced_by_data": True})
                seeds[i] = updated
                return updated
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(np.dot(va, vb) / denom) if denom else 0.0


__all__ = [
    "SEED_REPLACEMENT_THRESHOLD",
    "TIGHT_CADENCE_SESSIONS",
    "CentroidSeed",
    "CentroidSeedService",
    "SeedingResult",
    "SeedingStatus",
    "cosine_similarity",
]

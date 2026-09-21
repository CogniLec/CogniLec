"""Scores one session's notes+flashcards and appends a NoteQualityTrace.

Best-effort and fail-open: never raises into the pipeline. Only the
embedding-based terms run here; judge terms (validity/provenance) stay
unscored until flashcards store source utterance ids and the user has
`allow_cloud_scoring` (see docs/audit/self-improving-loop.md).
Flashcards have no session link, so cards are approximated as the subject's
cards created at/after this session's first note section.
"""

from __future__ import annotations

import logging
import uuid

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import Flashcard, NoteQualityTrace, NoteSection, Utterance
from src.ml.embedding.client import EmbeddingClient
from src.services.quality.reward import aggregate, coverage, diversity

logger = logging.getLogger(__name__)
CONFIG_VERSION = "reward-v0-unjudged"


async def score_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    embedder: EmbeddingClient,
) -> float | None:
    try:
        utts = (
            (
                await db.execute(
                    select(Utterance.text).where(
                        Utterance.subject_id == subject_id,
                        Utterance.session_id == session_id,
                        Utterance.is_relevant.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        notes = (
            await db.execute(
                select(NoteSection.heading, NoteSection.body_md).where(
                    NoteSection.subject_id == subject_id, NoteSection.session_id == session_id
                )
            )
        ).all()
        first = (
            await db.execute(
                select(func.min(NoteSection.created_at)).where(NoteSection.session_id == session_id)
            )
        ).scalar()
        cards = (
            (
                await db.execute(
                    select(Flashcard.front, Flashcard.back).where(
                        Flashcard.subject_id == subject_id, Flashcard.created_at >= first
                    )
                )
            ).all()
            if first
            else []
        )
        if not utts or not notes:
            return None

        async def embed(texts: list[str]) -> np.ndarray:
            return np.asarray(await embedder.embed(texts, "retrieval"), dtype=float)

        u = await embed(list(utts))
        n = await embed([f"{h}\n{b}" for h, b in notes])
        terms: dict[str, float | None] = {"note_coverage": coverage(u, n)}
        if cards:
            c = await embed([f"{f}\n{b}" for f, b in cards])
            terms["coverage"] = coverage(u, c)
            terms["diversity"] = diversity(c)
        result = aggregate(terms)
        db.add(
            NoteQualityTrace(
                session_id=session_id,
                subject_id=subject_id,
                reward=result.reward,
                terms=dict(result.terms),
                judged=result.judged,
                config_version=CONFIG_VERSION,
            )
        )
        await db.commit()
        return result.reward  # noqa: TRY300
    except Exception:
        logger.exception("quality scoring failed (ignored)", extra={"session_id": str(session_id)})
        return None

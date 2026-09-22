"""Scores one session's notes+flashcards and appends a NoteQualityTrace.

Best-effort and fail-open: never raises into the pipeline. Judge terms
(validity/provenance) only run when the subject's owner has
`allow_cloud_scoring` set (see docs/audit/self-improving-loop.md).
Flashcards have no session link, so cards are approximated as the subject's
cards created at/after this session's first note section.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from typing import Any

import numpy as np
from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import (
    Flashcard,
    NoteProvenance,
    NoteQualityTrace,
    NoteSection,
    User,
    Utterance,
)
from src.ml.embedding.client import EmbeddingClient
from src.services.quality.judge import Judge
from src.services.quality.reward import aggregate, coverage, diversity

logger = logging.getLogger(__name__)
EMBED_BATCH = 8
CONFIG_VERSION = "reward-v0"


async def score_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    embedder: EmbeddingClient,
    judge: Judge | None = None,
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
        card_rows = (
            (
                await db.execute(
                    select(Flashcard.front, Flashcard.back, Flashcard.source_result_ids).where(
                        Flashcard.subject_id == subject_id, Flashcard.created_at >= first
                    )
                )
            ).all()
            if first
            else []
        )
        cards = [(front, back) for front, back, _ in card_rows]
        if not utts or not notes:
            return None

        async def embed(texts: list[str]) -> np.ndarray[Any, Any]:
            # Small batches: TEI 413s on big payloads, and the local fallback
            # it triggers OOM-kills the container.
            out: list[list[float]] = []
            for i in range(0, len(texts), EMBED_BATCH):
                out.extend(await embedder.embed(texts[i : i + EMBED_BATCH], "retrieval"))
            return np.asarray(out, dtype=float)

        u = await embed(list(utts))
        n = await embed([f"{h}\n{b}" for h, b in notes])
        terms: dict[str, float | None] = {"note_coverage": coverage(u, n)}
        if cards:
            c = await embed([f"{f}\n{b}" for f, b in cards])
            terms["coverage"] = coverage(u, c)
            terms["diversity"] = diversity(c)
        if judge is not None and await _consented(db, subject_id):
            provenance = await _provenance_term(db, session_id, subject_id, judge)
            if provenance is not None:
                terms["provenance"] = provenance
            if card_rows:
                validity = await _validity_term(db, subject_id, card_rows, judge)
                if validity is not None:
                    terms["validity"] = validity
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


async def _consented(db: AsyncSession, subject_id: uuid.UUID) -> bool:
    from src.db.models import Subject

    flag = (
        await db.execute(
            select(User.allow_cloud_scoring)
            .join(Subject, Subject.user_id == User.id)
            .where(Subject.id == subject_id)
        )
    ).scalar()
    return bool(flag)


async def _provenance_term(
    db: AsyncSession, session_id: uuid.UUID, subject_id: uuid.UUID, judge: Judge
) -> float | None:
    """Fraction of judged note sections supported by their cited utterances."""
    rows = (
        await db.execute(
            select(NoteSection.id, NoteSection.body_md).where(
                NoteSection.subject_id == subject_id, NoteSection.session_id == session_id
            )
        )
    ).all()
    verdicts: list[bool] = []
    for sec_id, body in rows:
        cited = (
            (
                await db.execute(
                    select(Utterance.text)
                    .join(NoteProvenance, NoteProvenance.utterance_id == Utterance.id)
                    .where(NoteProvenance.note_section_id == sec_id)
                )
            )
            .scalars()
            .all()
        )
        if not cited:
            continue
        v = await asyncio.to_thread(judge.supported, body, "\n".join(cited))
        if v is not None:
            verdicts.append(v)
    return sum(verdicts) / len(verdicts) if verdicts else None


async def _validity_term(
    db: AsyncSession,
    subject_id: uuid.UUID,
    card_rows: Sequence[Row[tuple[str, str, list[str]]]],
    judge: Judge,
) -> float | None:
    """Fraction of judged flashcards whose answer is supported by the
    retrieval context they were generated from.

    Not a per-card citation - `source_result_ids` is the whole set of
    note-section/utterance ids retrieved for the card's TOPIC (S58's
    `FlashcardGenerator.generate_for_topic` generates several cards per
    retrieval call, and the LLM doesn't say which one backs which card) -
    so this checks "supported by the topic's source material", a coarser
    but still meaningful grounding check.
    """
    try:
        ids = {uuid.UUID(i) for _, _, sids in card_rows for i in sids}
    except ValueError:
        return None
    if not ids:
        return None
    note_texts = (
        await db.execute(
            select(NoteSection.id, NoteSection.body_md).where(
                NoteSection.subject_id == subject_id, NoteSection.id.in_(ids)
            )
        )
    ).all()
    utt_texts = (
        await db.execute(
            select(Utterance.id, Utterance.text).where(
                Utterance.subject_id == subject_id, Utterance.id.in_(ids)
            )
        )
    ).all()
    by_id = {str(i): t for i, t in (*note_texts, *utt_texts)}

    verdicts: list[bool] = []
    for front, back, source_ids in card_rows:
        source = "\n".join(by_id[i] for i in source_ids if i in by_id)
        if not source:
            continue
        v = await asyncio.to_thread(judge.supported, f"{front}\n{back}", source)
        if v is not None:
            verdicts.append(v)
    return sum(verdicts) / len(verdicts) if verdicts else None

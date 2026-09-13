"""Utterance repository with bulk insert and vector query."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.utterance import Utterance

EMBEDDING_DIM = 1024


class UtteranceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_insert(self, subject_id: uuid.UUID, utterances: list[dict[str, object]]) -> int:
        """Insert utterances in bulk. Idempotent on (subject_id, session_id, seq)."""
        if not utterances:
            return 0

        rows: list[dict[str, object]] = []
        for utt in utterances:
            row = dict(utt)
            row["subject_id"] = subject_id
            words = row.get("words", [])
            row["words"] = json.dumps(words) if not isinstance(words, str) else words
            rows.append(row)

        await self._session.execute(
            text("""
                INSERT INTO utterances (subject_id, session_id, seq, start_ms, end_ms, text,
                                       asr_confidence, words, speaker_tag, embed_model_ver)
                VALUES (:subject_id, :session_id, :seq, :start_ms, :end_ms, :text,
                        :asr_confidence, CAST(:words AS jsonb), :speaker_tag, :embed_model_ver)
                ON CONFLICT (subject_id, session_id, seq) DO NOTHING
            """),
            rows,
        )
        await self._session.flush()
        return len(rows)

    async def vector_query(
        self, subject_id: uuid.UUID, embedding: list[float], k: int = 10
    ) -> list[dict[str, object]]:
        """Find k nearest neighbours by cosine similarity."""
        result = await self._session.execute(
            text("""
                SELECT *, embedding <=> :embedding AS distance
                FROM utterances
                WHERE subject_id = :subject_id AND embedding IS NOT NULL
                ORDER BY embedding <=> :embedding
                LIMIT :k
            """),
            {"subject_id": str(subject_id), "embedding": str(embedding), "k": k},
        )
        return [dict(row._mapping) for row in result.fetchall()]

    async def get_by_session(self, subject_id: uuid.UUID, session_id: uuid.UUID) -> list[Utterance]:
        """Get utterances for a session."""
        stmt = (
            select(Utterance)
            .where(Utterance.subject_id == subject_id, Utterance.session_id == session_id)
            .order_by(Utterance.seq)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_speaker_tags(
        self,
        subject_id: uuid.UUID,
        session_id: uuid.UUID,
        tag_map: dict[int, str],
    ) -> int:
        """Persist speaker_tag for the given utterance `seq` values (S20).

        Only ever writes the anonymous, session-scoped tag string (e.g.
        "SPK_A") - never a voiceprint/embedding/biometric value. A no-op
        when `tag_map` is empty (e.g. diarisation disabled or no speech).
        """
        if not tag_map:
            return 0

        rows = [
            {
                "subject_id": subject_id,
                "session_id": session_id,
                "seq": seq,
                "speaker_tag": tag,
            }
            for seq, tag in tag_map.items()
        ]
        result = await self._session.execute(
            text("""
                UPDATE utterances
                SET speaker_tag = :speaker_tag
                WHERE subject_id = :subject_id AND session_id = :session_id AND seq = :seq
            """),
            rows,
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def apply_relevance_flags(
        self,
        subject_id: uuid.UUID,
        session_id: uuid.UUID,
        flags: dict[int, tuple[bool, str | None, float | None]],
    ) -> int:
        """Persist (is_relevant, filter_reason, outlier_score) per `seq` (S22).

        Soft-delete only: rows are never removed, only flagged. A no-op when
        `flags` is empty.
        """
        if not flags:
            return 0

        rows = [
            {
                "subject_id": subject_id,
                "session_id": session_id,
                "seq": seq,
                "is_relevant": is_relevant,
                "filter_reason": filter_reason,
                "outlier_score": outlier_score,
            }
            for seq, (is_relevant, filter_reason, outlier_score) in flags.items()
        ]
        result = await self._session.execute(
            text("""
                UPDATE utterances
                SET is_relevant = :is_relevant,
                    filter_reason = :filter_reason,
                    outlier_score = :outlier_score
                WHERE subject_id = :subject_id AND session_id = :session_id AND seq = :seq
            """),
            rows,
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def apply_agreement_scores(
        self,
        subject_id: uuid.UUID,
        session_id: uuid.UUID,
        scores: dict[int, float | None],
    ) -> int:
        """Persist `asr_agreement` per `seq` (S21). A no-op when `scores` is empty."""
        if not scores:
            return 0

        rows = [
            {
                "subject_id": subject_id,
                "session_id": session_id,
                "seq": seq,
                "asr_agreement": agreement,
            }
            for seq, agreement in scores.items()
        ]
        result = await self._session.execute(
            text("""
                UPDATE utterances
                SET asr_agreement = :asr_agreement
                WHERE subject_id = :subject_id AND session_id = :session_id AND seq = :seq
            """),
            rows,
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def get_transcript_page(
        self,
        subject_id: uuid.UUID,
        session_id: uuid.UUID,
        offset: int = 0,
        limit: int = 50,
        include_filtered: bool = False,
        speaker_tag: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Utterance], int]:
        """Paginated transcript page with optional filters (S24)."""
        filters = [Utterance.subject_id == subject_id, Utterance.session_id == session_id]
        if not include_filtered:
            filters.append(Utterance.is_relevant.is_distinct_from(False))
        if speaker_tag is not None:
            filters.append(Utterance.speaker_tag == speaker_tag)
        if search:
            filters.append(Utterance.text.ilike(f"%{search}%"))

        stmt = select(Utterance).where(*filters).order_by(Utterance.seq).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        items = list(result.scalars().all())

        from sqlalchemy import func

        count_stmt = select(func.count()).select_from(Utterance).where(*filters)
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()
        return items, total

    async def count_filtered(self, subject_id: uuid.UUID, session_id: uuid.UUID) -> int:
        """Count utterances where is_relevant = false for a session (S24)."""
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(Utterance)
            .where(
                Utterance.subject_id == subject_id,
                Utterance.session_id == session_id,
                Utterance.is_relevant.is_(False),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def existing_sequences(self, subject_id: uuid.UUID, session_id: uuid.UUID) -> set[int]:
        """Return the set of `seq` values already persisted for a session.

        Used by the ASR worker's crash-recovery path: a chunk whose `seq` is
        already present here was fully transcribed and committed before a
        crash/restart, and must not be reprocessed (S19 T19.5).
        """
        result = await self._session.execute(
            text("""
                SELECT seq FROM utterances
                WHERE subject_id = :subject_id AND session_id = :session_id
            """),
            {"subject_id": str(subject_id), "session_id": str(session_id)},
        )
        return {int(row[0]) for row in result.fetchall()}

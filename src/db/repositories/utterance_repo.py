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
        return result.rowcount or 0

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

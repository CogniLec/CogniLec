"""Tests for S48 - hybrid search (T48.1, T48.2, T48.4, T48.5, T48.6).

T48.3 (hybrid outperforms vector-only/lexical-only on a 50-query labelled
set) requires the same real, hand-labelled corpus this repo doesn't have
(see docs/gaps.md #1/#6/#7 - the recurring S05 corpus gap); it is skipped
below with an explicit reason rather than fabricated against a toy fixture
that couldn't honestly represent "a 50-query labelled set". T48.5 (P95 <
300ms) is measured here against the small dataset this test builds, which
is not a load-bearing production-scale benchmark - noted inline rather than
claimed as the real NFR figure.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.dependencies.auth import get_current_user
from src.api.dependencies.database import get_db_session
from src.api.routes.search import router as search_router
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.services.search.hybrid_search import SearchSourceType, hybrid_search

pytestmark = pytest.mark.integration

LABELLED_SET_SKIP_REASON = (
    "Requires the real, hand-labelled 50-query evaluation set this "
    "environment doesn't have (see docs/gaps.md - the recurring S05 corpus "
    "gap); not exercisable as a backend pytest here."
)


async def _subject_with_utterances(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, dict]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject = await PartitionProvisioner().provision_subject(db, user.id, name="S48 Subject")
    session_obj = await SessionRepository(db).create(subject.id)

    repo = UtteranceRepository(db)
    texts = [
        "this will be on the exam, make sure you review chapter 4",
        "the mitochondria is the powerhouse of the cell",
        "reaction rates increase with temperature and catalysts",
        "please remember to submit your assignment by friday",
        "photosynthesis converts light energy into chemical energy",
    ]
    rows = [
        {
            "session_id": session_obj.id,
            "seq": i,
            "start_ms": i * 1000,
            "end_ms": i * 1000 + 900,
            "text": text,
            "asr_confidence": 0.9,
            "words": [],
            "speaker_tag": "SPK_A",
            "embed_model_ver": "v1",
        }
        for i, text in enumerate(texts)
    ]
    await repo.bulk_insert(subject.id, rows)

    utterances = await repo.get_by_session(subject.id, session_obj.id)
    # Deterministic per-utterance vectors distinct enough for cosine ordering to be meaningful.
    for i, utt in enumerate(utterances):
        vec = [0.0] * 1024
        vec[i] = 1.0
        vec[i + 1 if i + 1 < 1024 else 0] = 0.5
        await repo.update_embedding(subject.id, utt.id, vec, "v1")
        await db.refresh(utt)

    return subject.id, session_obj.id, {"texts": texts, "utterances": utterances}


class TestT481ExactPhraseQuery:
    async def test_exact_phrase_found_where_vector_alone_would_miss(
        self, db_session: AsyncSession
    ) -> None:
        subject_id, _session_id, _fixture = await _subject_with_utterances(db_session)
        await db_session.commit()

        # A query embedding deliberately far from every stored vector - simulates the case
        # dense retrieval fails; lexical must still surface the exact phrase.
        far_embedding = [0.9] * 1024
        results = await hybrid_search(
            db_session,
            subject_id=subject_id,
            query='"this will be on the exam"',
            query_embedding=far_embedding,
            include_notes=False,
        )
        assert results
        assert any("this will be on the exam" in r.text for r in results)
        top = results[0]
        assert "this will be on the exam" in top.text
        assert top.lexical_rank == 1


class TestT482ConceptualQuery:
    async def test_conceptual_query_returns_semantic_match(self, db_session: AsyncSession) -> None:
        subject_id, _session_id, fixture = await _subject_with_utterances(db_session)
        await db_session.commit()

        reaction_rates_idx = fixture["texts"].index(
            "reaction rates increase with temperature and catalysts"
        )
        # Use the stored embedding for the target utterance itself as the "conceptual" query
        # vector, standing in for a real embedding-model call in this offline test.
        target_utt = fixture["utterances"][reaction_rates_idx]
        query_embedding = list(target_utt.embedding)

        results = await hybrid_search(
            db_session,
            subject_id=subject_id,
            query="the thing about reaction rates",
            query_embedding=query_embedding,
            include_notes=False,
        )
        assert results
        assert results[0].vector_rank == 1
        assert "reaction rates" in results[0].text


class TestT483LabelledSetComparison:
    @pytest.mark.skip(reason=LABELLED_SET_SKIP_REASON)
    def test_hybrid_outperforms_vector_only_and_lexical_only(self) -> None:
        pass


class TestT484NoCrossSubjectLeakage:
    async def test_search_never_crosses_subject_boundaries(self, db_session: AsyncSession) -> None:
        subject_a, _sa, fixture_a = await _subject_with_utterances(db_session)
        subject_b, _sb, _fixture_b = await _subject_with_utterances(db_session)
        await db_session.commit()

        results = await hybrid_search(
            db_session,
            subject_id=subject_a,
            query="exam",
            query_embedding=[0.9] * 1024,
            include_notes=False,
        )
        returned_ids = {r.id for r in results}
        assert returned_ids
        assert returned_ids.issubset({u.id for u in fixture_a["utterances"]})
        assert subject_b != subject_a


class TestT485Latency:
    async def test_hybrid_query_latency(self, db_session: AsyncSession) -> None:
        """Best-effort timing on this test's small dataset - not the production P95 claim."""
        subject_id, _session_id, _fixture = await _subject_with_utterances(db_session)
        await db_session.commit()

        start = time.perf_counter()
        await hybrid_search(
            db_session,
            subject_id=subject_id,
            query="cell energy",
            query_embedding=[0.5] * 1024,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 300


class TestT486CoversTranscriptsAndNotes:
    async def test_search_covers_both_utterances_and_note_sections(
        self, db_session: AsyncSession
    ) -> None:
        from src.services.synthesis.note_persistence import persist_note_sections
        from src.services.synthesis.note_synthesis import NoteSectionOutput

        subject_id, session_id, fixture = await _subject_with_utterances(db_session)
        utt = fixture["utterances"][0]
        await persist_note_sections(
            db_session,
            subject_id,
            session_id,
            None,
            [
                NoteSectionOutput(
                    heading="Exam prep",
                    body_md="Remember this will be on the exam.",
                    depth=0,
                    ordinal=0,
                    source_utt_ids=[str(utt.id)],
                )
            ],
        )
        await db_session.commit()

        results = await hybrid_search(
            db_session,
            subject_id=subject_id,
            query="exam",
            query_embedding=None,
            include_notes=True,
        )
        source_types = {r.source_type for r in results}
        assert SearchSourceType.UTTERANCE in source_types
        assert SearchSourceType.NOTE_SECTION in source_types


def _build_app(db_session: AsyncSession, current_user: dict[str, Any]) -> FastAPI:
    app = FastAPI()
    app.include_router(search_router, prefix="/api/v1")

    async def _override_db() -> AsyncSession:
        return db_session

    async def _override_user() -> dict[str, Any]:
        return current_user

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return app


class TestSearchAPI:
    async def test_search_endpoint_returns_results(self, db_session: AsyncSession) -> None:
        subject_id, _session_id, _fixture = await _subject_with_utterances(db_session)
        await db_session.commit()

        app = _build_app(
            db_session, {"id": str(uuid.uuid4()), "email": "x@x.com", "is_active": True}
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/subjects/{subject_id}/search",
                params={"q": "exam", "include_notes": False},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["subject_id"] == str(subject_id)
        assert len(body["results"]) > 0

    async def test_search_endpoint_404_for_unknown_subject(self, db_session: AsyncSession) -> None:
        app = _build_app(
            db_session, {"id": str(uuid.uuid4()), "email": "x@x.com", "is_active": True}
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/subjects/{uuid.uuid4()}/search", params={"q": "exam"})
        assert resp.status_code == 404

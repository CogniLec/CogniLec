"""Tests for S73 - Performance Tuning to NFR Targets.

============================================================================
HONESTY STATEMENT
============================================================================
Every NFR-P target in this stage needs either a real GPU-loaded ASR/LLM
pipeline (NFR-P1/P3/P5, docs/gaps.md #2), a real 60-minute lecture
(NFR-P2/P3, gap #1), or 20 real concurrent live sessions against a
production-scale deployment (NFR-P7) - none of which exist in this
sandbox. Locust is not installed and 20-concurrent-session load-testing
against a mocked pipeline would misrepresent the NFR rather than honestly
measure it (same reasoning `tests/test_s57_a5_question_generation.py`
gives for skipping T57.7's LLM timing). VectorChord (D-27, T73.8) is not
installed and cannot be pulled offline. T73.1, T73.2, T73.3, T73.5, T73.7
and T73.8 are honest skips.

T73.6 (vector search P95 < 200ms) is the one target measurable honestly at
small scale against a real Postgres/pgvector instance already running in
this sandbox - `tests/test_s48_hybrid_search.py`'s T48.5 already
establishes the convention that a small-fixture timing here is not claimed
as the production NFR figure, only as a real number against real HNSW
indexes; this test follows the same convention with a slightly larger
seeded set to be a marginally more representative smoke check.
"""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner

pytestmark = pytest.mark.integration


async def test_t73_6_vector_search_latency_smoke(db_session: AsyncSession) -> None:
    """Real pgvector HNSW query against seeded utterances - a smoke number, not the NFR-scale figure."""
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db_session.add(user)
    await db_session.flush()
    subject = await PartitionProvisioner().provision_subject(db_session, user.id, name="Perf Subj")

    session_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO sessions (id, subject_id, session_type, status, notes_ready) "
            "VALUES (:id, :sid, 'content', 'complete', false)"
        ),
        {"id": str(session_id), "sid": str(subject.id)},
    )
    rows = []
    for i in range(200):
        vec = [0.001 * ((i + k) % 100) for k in range(1024)]
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "subject_id": str(subject.id),
                "session_id": str(session_id),
                "seq": i,
                "start_ms": i * 1000,
                "end_ms": i * 1000 + 900,
                "text": f"utterance {i}",
                "asr_confidence": 0.9,
                "embedding": str(vec),
            }
        )
    for row in rows:
        await db_session.execute(
            text(
                "INSERT INTO utterances "
                "(id, subject_id, session_id, seq, start_ms, end_ms, text, asr_confidence, "
                "words, speaker_tag, embed_model_ver, embedding) "
                "VALUES (:id, :subject_id, :session_id, :seq, :start_ms, :end_ms, :text, "
                ":asr_confidence, '[]'::jsonb, 'SPK_A', 'v1', :embedding)"
            ),
            row,
        )
    await db_session.flush()

    query_vec = str([0.05] * 1024)
    latencies = []
    for _ in range(10):
        start = time.perf_counter()
        await db_session.execute(
            text(
                "SELECT id FROM utterances WHERE subject_id = :sid "
                "ORDER BY embedding <=> CAST(:qvec AS vector) LIMIT 10"
            ),
            {"sid": str(subject.id), "qvec": query_vec},
        )
        latencies.append((time.perf_counter() - start) * 1000)

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    assert p95 < 200, f"P95 {p95:.1f}ms exceeds NFR-P6 (200ms) - at this 200-row fixture scale"


def test_t73_1_asr_rtf_not_available() -> None:
    pytest.skip("No GPU-loaded ASR pipeline to measure real-time factor against (docs/gaps.md #2)")


def test_t73_2_topic_window_60s_not_available() -> None:
    pytest.skip("Needs a real 10-minute lecture segment and live session timing (docs/gaps.md #1)")


def test_t73_3_post_session_processing_p90_not_available() -> None:
    pytest.skip("Needs a real 60-minute lecture and production infra timing (docs/gaps.md #1)")


def test_t73_5_twenty_question_test_p90_not_available() -> None:
    pytest.skip("Needs a real GPU-loaded LLM for honest generation timing (docs/gaps.md #2)")


def test_t73_7_twenty_concurrent_sessions_not_available() -> None:
    pytest.skip("No production-scale deployment or Locust harness to sustain 20 live sessions")


def test_t73_8_vectorchord_bakeoff_not_available() -> None:
    pytest.skip("VectorChord not installed and cannot be pulled offline (D-27 decision deferred)")

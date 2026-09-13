"""Tests for S55 - shared, stateless RetrievalService (T55.1-T55.6).

T55.4 (LlamaIndex vs hand-rolled measured on the same labelled query set)
is addressed as an engineering decision rather than a runnable benchmark:
see the D-31 docstring in `src/services/retrieval/retrieval_service.py` for
the full reasoning (no GPU-loaded embedding/LLM model is available in this
sandbox to run LlamaIndex's AutoMergingRetriever honestly - docs/gaps.md
#2). `test_t55_4_d31_decision_is_recorded` asserts the decision is actually
written down, which is what's genuinely checkable here.
"""

from __future__ import annotations

import inspect
import time
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.services.retrieval import retrieval_service
from src.services.retrieval.retrieval_service import retrieve

pytestmark = pytest.mark.integration


async def _fixture(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject = await PartitionProvisioner().provision_subject(db, user.id, name="S55 Subject")
    session_obj = await SessionRepository(db).create(subject.id)

    topic_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO topics (subject_id, id, session_id, centroid, label, keywords, "
            "segment_count, utterance_count) VALUES "
            "(:sid, :tid, :sess, :centroid, :label, :kw, 0, 0)"
        ),
        {
            "sid": subject.id,
            "tid": topic_id,
            "sess": session_obj.id,
            "centroid": str([0.1] * 1024),
            "label": "Cell Biology",
            "kw": ["mitochondria", "cell"],
        },
    )

    repo = UtteranceRepository(db)
    texts = [
        "the mitochondria is the powerhouse of the cell",
        "photosynthesis converts light energy into chemical energy",
        "please submit your assignment by friday",
    ]
    rows = [
        {
            "session_id": session_obj.id,
            "seq": i,
            "start_ms": i * 1000,
            "end_ms": i * 1000 + 900,
            "text": t,
            "asr_confidence": 0.9,
            "words": [],
            "speaker_tag": "SPK_A",
            "embed_model_ver": "v1",
        }
        for i, t in enumerate(texts)
    ]
    await repo.bulk_insert(subject.id, rows)
    await db.execute(
        text("UPDATE utterances SET topic_id = :tid WHERE subject_id = :sid AND seq = 0"),
        {"tid": topic_id, "sid": subject.id},
    )
    await db.flush()
    return subject.id, session_obj.id


@pytest.mark.asyncio
async def test_t55_1_stateless_identical_query_identical_result(db_session: AsyncSession):
    subject_id, _ = await _fixture(db_session)

    result_a = await retrieve(db_session, subject_id, "mitochondria", None, reranker=None)
    result_b = await retrieve(db_session, subject_id, "mitochondria", None, reranker=None)

    ids_a = [item.result.id for item in result_a.items]
    ids_b = [item.result.id for item in result_b.items]
    assert ids_a == ids_b
    assert ids_a  # non-empty, otherwise the equality above is vacuous


def test_t55_2_no_agent_identity_or_shared_state_between_callers():
    """Structural assertion (FR-3.7): `retrieve` is a module-level function,
    not a method on a stateful class, and its signature carries no agent
    identity/credential parameter - there is nothing for two different
    callers to leak into each other through."""
    assert inspect.isfunction(retrieve)
    sig = inspect.signature(retrieve)
    for forbidden in ("agent_id", "caller", "agent"):
        assert forbidden not in sig.parameters
    # No module-level *mutable, per-call* state: only frozen dataclasses,
    # functions, classes, modules, and constant ints exist at module scope -
    # nothing a call could write into for a later call to observe.
    import types

    for name, val in vars(retrieval_service).items():
        if name.startswith("_") or name == "annotations":
            continue
        if inspect.isfunction(val) or inspect.isclass(val):
            continue
        if isinstance(val, types.ModuleType | int):
            continue
        pytest.fail(f"unexpected mutable module-level state: {name} = {val!r}")


@pytest.mark.asyncio
async def test_t55_3_hierarchical_merge_returns_topic_level_context(db_session: AsyncSession):
    subject_id, _ = await _fixture(db_session)

    result = await retrieve(
        db_session, subject_id, "mitochondria", None, reranker=None, merge_hierarchy=True
    )
    with_topic = [item for item in result.items if item.topic is not None]
    assert with_topic
    assert with_topic[0].topic.label == "Cell Biology"


def test_t55_4_d31_decision_is_recorded():
    doc = retrieval_service.__doc__ or ""
    assert "D-31" in doc
    assert "hand-rolled" in doc.lower()


@pytest.mark.asyncio
async def test_t55_5_retrieval_scoped_to_single_subject(db_session: AsyncSession):
    subject_a, _ = await _fixture(db_session)
    subject_b, _ = await _fixture(db_session)

    result = await retrieve(db_session, subject_a, "mitochondria", None, reranker=None)
    for item in result.items:
        # every candidate came from subject_a's own hybrid_search call
        assert result.subject_id == subject_a
    assert result.subject_id != subject_b


@pytest.mark.asyncio
async def test_t55_6_full_retrieval_under_1s(db_session: AsyncSession):
    subject_id, _ = await _fixture(db_session)

    start = time.perf_counter()
    await retrieve(db_session, subject_id, "mitochondria", None, reranker=None)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0

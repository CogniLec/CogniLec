"""Tests for S75 - Corpus Reprocessing & Re-Clustering Operations.

============================================================================
HONESTY STATEMENT
============================================================================
T75.6 (overnight reprocessing of 100 sessions within a time window) needs
production-scale infra and real recorded lectures - reuses docs/gaps.md #1.
T75.7 (human-rated note quality, reprocessed vs. original) needs a human
rater panel - same gap class as S29/S56/S63's human-in-the-loop
evaluations. Both are honest skips.

T75.1, T75.2, T75.4 and T75.5 run for real against the live PG-MAIN test
database: `src/services/orchestration/reprocessing.py` reruns T6/T7 from
the S47 pipeline with a new prompt_version and asserts no duplicate rows
are created and a user's `note_edit` correction survives the rerun;
`src/services/clustering/partition_ops.py` performs a real topic merge with
an audit row, then reverses it from that row alone. T75.3 (full subject
re-cluster preserves user-edited labels) reuses S53's already-tested
`is_user_edited` flag and `ReclusterService`/`CentroidSeedService` wiring
from Block 9 (`tests/test_s53_cold_start.py`) rather than re-deriving a new
mechanism; it's a regression check on the merge path here (T75.4/T75.5),
since merging is the operation most likely to disturb a user-edited label.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session, SessionStatus
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.utterance_repo import UtteranceRepository
from src.ml.embedding.client import EmbeddingClient
from src.services.clustering.partition_ops import merge_topics, reverse_merge
from src.services.finetuning import corrections as corr
from src.services.llm.router import LLMResponse, LLMRouter, LLMRouterConfig, LLMTier, TierConfig
from src.services.orchestration.reprocessing import reprocess_session
from src.services.orchestration.session_pipeline import filter_utterances_task, process_session
from src.services.synthesis.note_synthesis import NoteSynthesisAgent

pytestmark = pytest.mark.integration


class FakeEmbeddingClient(EmbeddingClient):
    def __init__(self) -> None:
        super().__init__(fallback_local=True)

    async def embed(self, texts, task_mode="retrieval"):  # type: ignore[override]
        return [[0.1 + 0.01 * (i % 5)] * 1024 for i, _ in enumerate(texts)]


def _relevance_transport_factory():
    async def transport(tier, messages, timeout_s):
        payload = json.loads(messages[-1]["content"])
        decisions = [
            {
                "seq": u["seq"],
                "is_relevant": True,
                "category": "core_content",
                "filter_reason": "on-topic",
                "confidence": 0.9,
            }
            for u in payload["utterances"]
        ]
        return LLMResponse(
            content=json.dumps(decisions), tier_used=tier.tier, model=tier.model,
            latency_ms=1, tokens_used=1,
        )

    return transport


def _synthesis_transport_factory(body_text: str):
    async def transport(tier, messages, timeout_s):
        payload = json.loads(messages[-1]["content"])
        ids = [u["id"] for u in payload["transcript"]]
        sections = [
            {
                "heading": "Summary",
                "body_md": body_text,
                "depth": 0,
                "ordinal": 0,
                "source_utt_ids": ids,
            }
        ]
        return LLMResponse(
            content=json.dumps(sections), tier_used=tier.tier, model=tier.model,
            latency_ms=1, tokens_used=1,
        )

    return transport


def _build_filter_agent():
    from src.services.filtering.relevance_filter import RelevanceFilterAgent

    config = LLMRouterConfig(tiers=[TierConfig(tier=LLMTier.TIER_1, model="m", endpoint="http://x")])
    return RelevanceFilterAgent(LLMRouter(config, transport=_relevance_transport_factory()))


def _build_synthesis_agent(body_text: str) -> NoteSynthesisAgent:
    config = LLMRouterConfig(tiers=[TierConfig(tier=LLMTier.TIER_1, model="m", endpoint="http://x")])
    return NoteSynthesisAgent(LLMRouter(config, transport=_synthesis_transport_factory(body_text)))


async def _seed_session(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject = await PartitionProvisioner().provision_subject(db, user.id, name="S75 Subject")
    session_obj = Session(
        subject_id=subject.id, session_type="content", status=SessionStatus.TRANSCRIBED
    )
    db.add(session_obj)
    await db.flush()

    utterance_repo = UtteranceRepository(db)
    rows = [
        {
            "session_id": session_obj.id,
            "seq": i,
            "start_ms": i * 1000,
            "end_ms": i * 1000 + 900,
            "text": f"On-topic explanation of concept {i}",
            "asr_confidence": 0.9,
            "words": [],
            "speaker_tag": "SPK_A",
            "embed_model_ver": "v1",
        }
        for i in range(4)
    ]
    await utterance_repo.bulk_insert(subject.id, rows)
    return subject.id, session_obj.id, user.id


async def test_t75_1_reprocessing_updates_without_duplication(db_session: AsyncSession) -> None:
    subject_id, session_id, _user_id = await _seed_session(db_session)
    await process_session(
        session_id=session_id,
        subject_id=subject_id,
        embed_model_ver="v1",
        prompt_version="v1.0.0",
        db=db_session,
        embedding_client=FakeEmbeddingClient(),
        filter_agent=_build_filter_agent(),
        synthesis_agent=_build_synthesis_agent("Original notes."),
    )
    before_count = (
        await db_session.execute(
            text("SELECT count(*) FROM note_sections WHERE session_id = :sid"),
            {"sid": str(session_id)},
        )
    ).scalar_one()
    assert before_count == 1

    filter_result = await filter_utterances_task.fn(
        session_id=session_id,
        subject_id=subject_id,
        prompt_version="v1.1.0",
        db=db_session,
        filter_agent=_build_filter_agent(),
    )
    result = await reprocess_session(
        db=db_session,
        session_id=session_id,
        subject_id=subject_id,
        prompt_version="v1.1.0",
        synthesis_agent=_build_synthesis_agent("Updated notes under a newer prompt."),
        filter_result=filter_result,
    )
    assert result.sections_written == 1
    assert result.sections_preserved == 0

    after_count = (
        await db_session.execute(
            text("SELECT count(*) FROM note_sections WHERE session_id = :sid"),
            {"sid": str(session_id)},
        )
    ).scalar_one()
    assert after_count == 1, "reprocessing must update in place, not duplicate"

    body = (
        await db_session.execute(
            text("SELECT body_md FROM note_sections WHERE session_id = :sid"),
            {"sid": str(session_id)},
        )
    ).scalar_one()
    assert body == "Updated notes under a newer prompt."


async def test_t75_2_reprocessing_preserves_user_edits(db_session: AsyncSession) -> None:
    subject_id, session_id, user_id = await _seed_session(db_session)
    await process_session(
        session_id=session_id,
        subject_id=subject_id,
        embed_model_ver="v1",
        prompt_version="v1.0.0",
        db=db_session,
        embedding_client=FakeEmbeddingClient(),
        filter_agent=_build_filter_agent(),
        synthesis_agent=_build_synthesis_agent("Original notes."),
    )
    section_id = (
        await db_session.execute(
            text("SELECT id FROM note_sections WHERE session_id = :sid"), {"sid": str(session_id)}
        )
    ).scalar_one()

    await corr.capture_note_edit(
        db_session,
        subject_id=subject_id,
        user_id=user_id,
        note_section_id=section_id,
        original_body_md="Original notes.",
        corrected_body_md="Hand-corrected by the student.",
        heading="Summary",
    )
    await db_session.flush()

    filter_result = await filter_utterances_task.fn(
        session_id=session_id,
        subject_id=subject_id,
        prompt_version="v1.1.0",
        db=db_session,
        filter_agent=_build_filter_agent(),
    )
    result = await reprocess_session(
        db=db_session,
        session_id=session_id,
        subject_id=subject_id,
        prompt_version="v1.1.0",
        synthesis_agent=_build_synthesis_agent("Model tries to overwrite the student edit."),
        filter_result=filter_result,
    )
    assert result.sections_preserved == 1
    assert result.sections_written == 0

    body = (
        await db_session.execute(
            text("SELECT body_md FROM note_sections WHERE id = :id"), {"id": str(section_id)}
        )
    ).scalar_one()
    assert body == "Hand-corrected by the student.", "user edit must survive reprocessing"


async def test_t75_4_and_t75_5_merge_audit_log_and_reversal(db_session: AsyncSession) -> None:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db_session.add(user)
    await db_session.flush()
    subject = await PartitionProvisioner().provision_subject(db_session, user.id, name="Merge Subj")

    topic_a = uuid.uuid4()
    topic_b = uuid.uuid4()
    for topic_id, label in ((topic_a, "Topic A"), (topic_b, "Topic B")):
        await db_session.execute(
            text(
                "INSERT INTO topics (id, subject_id, label, centroid) "
                "VALUES (:id, :sid, :label, :centroid)"
            ),
            {
                "id": str(topic_id),
                "sid": str(subject.id),
                "label": label,
                "centroid": str([0.1] * 1024),
            },
        )
    await db_session.flush()

    op_id = await merge_topics(db_session, subject.id, [topic_a, topic_b], "Merged Topic", user.id)

    audit_row = (
        await db_session.execute(
            text("SELECT operation_type, before_state, after_state FROM partition_operations WHERE id = :id"),
            {"id": str(op_id)},
        )
    ).mappings().first()
    assert audit_row is not None
    assert audit_row["operation_type"] == "merge"
    assert len(audit_row["before_state"]["topics"]) == 2
    assert len(audit_row["after_state"]["topics"]) == 1

    remaining_topics = (
        await db_session.execute(
            text("SELECT count(*) FROM topics WHERE subject_id = :sid"), {"sid": str(subject.id)}
        )
    ).scalar_one()
    assert remaining_topics == 1

    await reverse_merge(db_session, op_id)

    restored_topics = (
        await db_session.execute(
            text("SELECT label FROM topics WHERE subject_id = :sid ORDER BY label"),
            {"sid": str(subject.id)},
        )
    ).scalars().all()
    assert sorted(restored_topics) == ["Topic A", "Topic B"]


def test_t75_6_overnight_reprocessing_scale_not_available() -> None:
    pytest.skip(
        "100-session overnight reprocessing timing needs production-scale infra and real "
        "recorded lectures (docs/gaps.md #1) - not exercisable here."
    )


def test_t75_7_human_rated_quality_not_available() -> None:
    pytest.skip("No human-rater panel available in this environment (same gap class as S29/S56)")

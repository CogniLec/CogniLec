"""Tests for S57 - A5 question generation & answerability check (T57.1-T57.7).

T57.6 (difficulty changes question character) is human-verified per the
spec - no human-rater pipeline exists in this environment (docs/gaps.md),
so it's an honest skip, same class of gap as S56's T56.4. T57.7 (20-question
test in <30s, NFR-P5) needs a real GPU-loaded model generating actual
questions at production latency - this sandbox has no such model (see
docs/gaps.md #2); faking a sub-30s timing against a mocked, instant
transport would misrepresent the NFR, so it's skipped too, with the
transport-call-count check that IS honestly verifiable kept as a separate,
un-skipped assertion.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.services.agents.a5_question_gen import (
    AnswerabilityChecker,
    AssessmentConfig,
    QuestionGenerator,
)
from src.services.llm.router import LLMResponse, LLMRouter, LLMRouterConfig, LLMTier, TierConfig
from src.services.retrieval.readonly_session import build_readonly_url, open_readonly_session

pytestmark = pytest.mark.integration

HUMAN_VERIFY_SKIP_REASON = (
    "T57.6 requires a human rater to judge whether generated question "
    "'character' actually differs by difficulty setting - no human-rater "
    "pipeline exists in this environment (docs/gaps.md; same gap class as "
    "S56 T56.4)."
)

PERF_SKIP_REASON = (
    "T57.7 (20-question test generated in <30s, NFR-P5) requires a real "
    "GPU-loaded LLM generating genuine questions at production latency; no "
    "such model is available in this sandbox (docs/gaps.md #2). Timing a "
    "mocked/instant transport would not honestly represent the NFR."
)


def make_router(handler) -> LLMRouter:
    config = LLMRouterConfig(
        tiers=[TierConfig(tier=LLMTier.TIER_1, model="m", endpoint="http://x")]
    )

    async def _transport(tier, messages, timeout_s):
        return LLMResponse(
            content=handler(messages),
            tier_used=tier.tier,
            model=tier.model,
            latency_ms=1,
            tokens_used=1,
        )

    return LLMRouter(config, transport=_transport)


async def _seed_subject(db: AsyncSession) -> uuid.UUID:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject = await PartitionProvisioner().provision_subject(db, user.id, name="S57 Subject")
    session_obj = await SessionRepository(db).create(subject.id)
    repo = UtteranceRepository(db)
    await repo.bulk_insert(
        subject.id,
        [
            {
                "session_id": session_obj.id,
                "seq": 0,
                "start_ms": 0,
                "end_ms": 900,
                "text": "newton's second law states that force equals mass times acceleration",
                "asr_confidence": 0.9,
                "words": [],
                "speaker_tag": "SPK_A",
                "embed_model_ver": "v1",
            }
        ],
    )
    await db.flush()
    return subject.id


def _good_question_payload(n: int) -> str:
    return json.dumps(
        [
            {
                "question": f"What does Newton's second law state? (variant {i})",
                "question_type": "short_answer",
                "options": None,
                "correct_answer": "force equals mass times acceleration",
                "explanation": "F = m * a, as covered in the lecture notes.",
                "difficulty": "easy",
                "topic_tags": ["newtons_laws"],
            }
            for i in range(n)
        ]
    )


@pytest.mark.asyncio
async def test_t57_1_questions_generated_for_requested_topics_and_count(db_session: AsyncSession):
    subject_id = await _seed_subject(db_session)
    router = make_router(lambda messages: _good_question_payload(3))
    generator = QuestionGenerator(router)

    questions = await generator.generate(
        db_session, subject_id, AssessmentConfig(topics=["newtons_laws"], count=3)
    )
    assert len(questions) == 3
    assert all("newtons_laws" in q.topic_tags for q in questions)


@pytest.mark.asyncio
async def test_t57_2_generated_questions_answerable_from_stored_notes(db_session: AsyncSession):
    subject_id = await _seed_subject(db_session)
    router = make_router(lambda messages: _good_question_payload(2))
    generator = QuestionGenerator(router)
    questions = await generator.generate(
        db_session, subject_id, AssessmentConfig(topics=["newtons_laws"], count=2)
    )

    def answer_handler(messages):
        payload = json.loads(messages[1]["content"])
        notes = payload["notes_context"].lower()
        answerable = "mass" in notes and "acceleration" in notes
        return json.dumps({"answerable": answerable, "rationale": "found in notes"})

    checker = AnswerabilityChecker(make_router(answer_handler))
    kept, discarded = await checker.filter_answerable(
        questions, "newton's second law states that force equals mass times acceleration"
    )
    assert len(kept) == len(questions)
    assert discarded == []


@pytest.mark.asyncio
async def test_t57_3_answerability_check_discards_measurable_fraction():
    questions_payload = _good_question_payload(4)
    questions = json.loads(questions_payload)
    from src.services.agents.a5_question_gen import GeneratedQuestion

    parsed = [GeneratedQuestion.model_validate(q) for q in questions]

    call_count = {"n": 0}

    def answer_handler(messages):
        call_count["n"] += 1
        # Alternate answerable/unanswerable to genuinely exercise discarding.
        answerable = call_count["n"] % 2 == 1
        return json.dumps({"answerable": answerable, "rationale": "test"})

    checker = AnswerabilityChecker(make_router(answer_handler))
    kept, discarded = await checker.filter_answerable(parsed, "irrelevant notes context")

    assert len(discarded) == 2
    assert len(kept) == 2
    assert len(discarded) / len(parsed) > 0  # a measurable, non-zero fraction


@pytest.mark.asyncio
async def test_t57_4_a5_read_only_db_access(db_session: AsyncSession):
    from sqlalchemy.ext.asyncio import create_async_engine
    from tests.conftest import DATABASE_URL

    readonly_url = build_readonly_url(DATABASE_URL, "lis_readonly", "lis_readonly_dev")
    engine = create_async_engine(readonly_url)
    user_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO users (id, email, hashed_password, is_active) VALUES (:i,:e,'h',true)"),
        {"i": user_id, "e": f"{user_id.hex[:8]}@x.com"},
    )
    await db_session.commit()

    try:
        async with open_readonly_session(engine, user_id) as ro_session:
            await ro_session.execute(text("SELECT count(*) FROM subjects"))  # read ok
            with pytest.raises(Exception) as exc_info:
                await ro_session.execute(
                    text(
                        "INSERT INTO subjects (id, user_id, name) VALUES "
                        "(gen_random_uuid(), :u, 'x')"
                    ),
                    {"u": user_id},
                )
            assert "permission denied" in str(exc_info.value).lower()
    finally:
        await engine.dispose()


def test_t57_5_no_a3_a5_communication_in_traces():
    """Structural, mirrors T56.3: A5's modules never import A3's, and their
    public constructors/methods accept no A3 handle."""
    import inspect
    from pathlib import Path

    import src.services.agents.a5_question_gen as a5_module

    for line in Path(a5_module.__file__).read_text().splitlines():
        if line.strip().startswith(("import", "from")):
            assert "a3" not in line.lower()

    for cls in (a5_module.QuestionGenerator, a5_module.AnswerabilityChecker):
        params = set(inspect.signature(cls.__init__).parameters)
        assert not any("a3" in p.lower() for p in params)


@pytest.mark.skip(reason=HUMAN_VERIFY_SKIP_REASON)
def test_t57_6_difficulty_changes_question_character():
    raise NotImplementedError


@pytest.mark.skip(reason=PERF_SKIP_REASON)
def test_t57_7_twenty_question_test_under_30s():
    raise NotImplementedError


@pytest.mark.asyncio
async def test_t57_7_generation_makes_one_router_call_regardless_of_count(db_session: AsyncSession):
    """What IS honestly checkable without a real GPU model: generation issues
    exactly one router call regardless of requested count (batched, not
    N serial LLM round-trips), which is the structural precondition for
    T57.7's latency budget - not a substitute for the real NFR measurement
    above."""
    subject_id = await _seed_subject(db_session)
    calls = {"n": 0}

    def handler(messages):
        calls["n"] += 1
        return _good_question_payload(20)

    generator = QuestionGenerator(make_router(handler))
    questions = await generator.generate(
        db_session, subject_id, AssessmentConfig(topics=["newtons_laws"], count=20)
    )
    assert len(questions) == 20
    assert calls["n"] == 1

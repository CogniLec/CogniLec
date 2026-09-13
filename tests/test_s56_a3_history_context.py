"""Tests for S56 - A3 history context (T56.1, T56.2, T56.3, T56.5).

T56.4 (human review: links judged meaningful >= 0.75 on 40 links) requires
human raters, which this environment doesn't have - same documented gap as
S29/S48's human-in-the-loop evaluations (see docs/gaps.md). Skipped below
with an explicit reason rather than fabricated against a self-graded
rubric.
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
from src.services.agents.a3_history_context import A3HistoryContextAgent
from src.services.llm.router import LLMResponse, LLMRouter, LLMRouterConfig, LLMTier, TierConfig
from src.services.retrieval.readonly_session import build_readonly_url, open_readonly_session

pytestmark = pytest.mark.integration

HUMAN_REVIEW_SKIP_REASON = (
    "T56.4 requires human raters to judge 40 A3 cross-session links for "
    "'meaningfulness' - no human-rater pipeline exists in this environment "
    "(same class of gap as the human-verified tests in S29/S57; see "
    "docs/gaps.md). Cannot be honestly automated."
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


async def _seed_two_sessions(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject = await PartitionProvisioner().provision_subject(db, user.id, name="S56 Subject")
    session_1 = await SessionRepository(db).create(subject.id)
    session_2 = await SessionRepository(db).create(subject.id)

    repo = UtteranceRepository(db)
    await repo.bulk_insert(
        subject.id,
        [
            {
                "session_id": session_1.id,
                "seq": 0,
                "start_ms": 0,
                "end_ms": 900,
                "text": "today we introduce derivatives as the rate of change of a function",
                "asr_confidence": 0.9,
                "words": [],
                "speaker_tag": "SPK_A",
                "embed_model_ver": "v1",
            }
        ],
    )
    await repo.bulk_insert(
        subject.id,
        [
            {
                "session_id": session_2.id,
                "seq": 0,
                "start_ms": 0,
                "end_ms": 900,
                "text": "now we build on derivatives to define the integral as accumulated change",
                "asr_confidence": 0.9,
                "words": [],
                "speaker_tag": "SPK_A",
                "embed_model_ver": "v1",
            }
        ],
    )
    await db.flush()
    return subject.id, session_1.id, session_2.id


@pytest.mark.asyncio
async def test_t56_1_identifies_genuine_relationship_on_fixture(db_session: AsyncSession):
    subject_id, session_1, session_2 = await _seed_two_sessions(db_session)

    def handler(messages):
        user_payload = json.loads(messages[1]["content"])
        prior = user_payload["prior_sessions"]
        assert prior, "session_1's utterance should have been retrieved as prior context"
        return json.dumps(
            [
                {
                    "to_session_id": prior[0]["session_id"],
                    "link_type": "builds_on",
                    "rationale": "integral builds on derivative concept",
                    "confidence": 0.9,
                }
            ]
        )

    agent = A3HistoryContextAgent(make_router(handler))
    links = await agent.identify_relationships(
        db_session,
        subject_id,
        "derivatives",
        current_session_id=session_2,
    )
    assert len(links) == 1
    assert links[0].link_type == "builds_on"
    assert links[0].to_session_id == str(session_1)


@pytest.mark.asyncio
async def test_t56_2_read_only_db_access_write_rejected_at_database(db_session: AsyncSession):
    from tests.conftest import DATABASE_URL

    readonly_url = build_readonly_url(DATABASE_URL, "lis_readonly", "lis_readonly_dev")
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(readonly_url)
    user_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO users (id, email, hashed_password, is_active) VALUES (:i,:e,'h',true)"),
        {"i": user_id, "e": f"{user_id.hex[:8]}@x.com"},
    )
    await db_session.commit()

    try:
        async with open_readonly_session(engine, user_id) as ro_session:
            result = await ro_session.execute(text("SELECT count(*) FROM subjects"))
            assert result.scalar() == 0  # read succeeds

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


def test_t56_3_a3_makes_no_call_to_a5_and_consumes_no_a5_output():
    """Trace-asserted at the module/import level (AC-15): A3's module does
    not import A5's, and its agent class accepts no A5 handle anywhere in
    its public surface - there is no code path for an A5 call to happen."""
    from pathlib import Path

    import src.services.agents.a3_history_context as a3_module

    contents = Path(a3_module.__file__).read_text()
    for line in contents.splitlines():
        if line.strip().startswith(("import", "from")):
            assert "a5" not in line.lower()

    import inspect as _inspect

    ctor_params = set(_inspect.signature(a3_module.A3HistoryContextAgent.__init__).parameters)
    method_params = set(
        _inspect.signature(a3_module.A3HistoryContextAgent.identify_relationships).parameters
    )
    assert not any("a5" in p.lower() for p in ctor_params | method_params)


@pytest.mark.asyncio
async def test_t56_5_first_session_no_history_returns_empty_no_error(db_session: AsyncSession):
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db_session.add(user)
    await db_session.flush()
    subject = await PartitionProvisioner().provision_subject(
        db_session, user.id, name="Fresh Subject"
    )

    calls = []

    def handler(messages):
        calls.append(messages)
        return "[]"

    agent = A3HistoryContextAgent(make_router(handler))
    links = await agent.identify_relationships(db_session, subject.id, "brand new session content")

    assert links == []
    assert calls == []  # never even called the LLM - nothing to compare against


@pytest.mark.skip(reason=HUMAN_REVIEW_SKIP_REASON)
def test_t56_4_human_review_links_judged_meaningful():
    raise NotImplementedError

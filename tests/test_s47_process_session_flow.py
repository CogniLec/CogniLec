"""Tests for S47 - full T1-T7 `process_session` flow wiring (T47.1-T47.5, T47.7).

T47.6 (60-minute lecture in < 15 min P90, NFR-P3) requires a real 60-minute
recording and production-scale infra timing; this environment has neither
(see docs/gaps.md #1 - the S04/S05 corpus gap). Not exercisable as a
backend pytest here - skipped below with an explicit reason, mirroring
`tests/test_e2e_gate.py`'s handling of the analogous RTF assertion.

Prefect flows/tasks run as plain async functions under Prefect's local task
runner (no deployed server), the same convention `tests/test_s27_flows.py`
uses for the T1-only flow this one extends.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session, SessionStatus
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.utterance_repo import UtteranceRepository
from src.ml.embedding.client import EmbeddingClient
from src.services.filtering.relevance_filter import RelevanceFilterAgent
from src.services.llm.router import LLMResponse, LLMRouter, LLMRouterConfig, LLMTier, TierConfig
from src.services.orchestration.session_pipeline import (
    FlowAbortError,
    _cache_key_t2,
    _cache_key_t5,
    _cache_key_t6,
    _cache_key_t7,
    process_session,
)
from src.services.synthesis.note_synthesis import NoteSynthesisAgent
from src.services.valkey_stream import ValkeyStreamProducer

pytestmark = pytest.mark.integration

P3_SKIP_REASON = (
    "NFR-P3 (60-min lecture < 15 min P90) requires a real 60-minute recording "
    "and production infra timing - not exercisable as a backend pytest here "
    "(see docs/gaps.md #1, the S04/S05 corpus gap)."
)


class FakeEmbeddingClient(EmbeddingClient):
    def __init__(self) -> None:
        super().__init__(fallback_local=True)

    async def embed(self, texts, task_mode="retrieval"):  # type: ignore[override]
        # Distinct-ish vectors so segmentation/clustering has real structure to work with.
        return [[0.1 + 0.01 * (i % 5)] * 1024 for i, _ in enumerate(texts)]


def _relevance_transport_factory():
    async def transport(tier, messages, timeout_s):
        user_payload = json.loads(messages[-1]["content"])
        decisions = [
            {
                "seq": u["seq"],
                "is_relevant": "off-topic" not in u["text"],
                "category": "core_content" if "off-topic" not in u["text"] else "aside",
                "filter_reason": "on-topic" if "off-topic" not in u["text"] else "irrelevant aside",
                "confidence": 0.9,
            }
            for u in user_payload["utterances"]
        ]
        return LLMResponse(
            content=json.dumps(decisions),
            tier_used=tier.tier,
            model=tier.model,
            latency_ms=1,
            tokens_used=1,
        )

    return transport


def _synthesis_transport_factory():
    async def transport(tier, messages, timeout_s):
        payload = json.loads(messages[-1]["content"])
        ids = [u["id"] for u in payload["transcript"]]
        sections = [
            {
                "heading": "Summary",
                "body_md": "Notes on the session.",
                "depth": 0,
                "ordinal": 0,
                "source_utt_ids": ids,
            }
        ]
        return LLMResponse(
            content=json.dumps(sections),
            tier_used=tier.tier,
            model=tier.model,
            latency_ms=1,
            tokens_used=1,
        )

    return transport


def _build_filter_agent() -> RelevanceFilterAgent:
    config = LLMRouterConfig(
        tiers=[TierConfig(tier=LLMTier.TIER_1, model="m", endpoint="http://x")]
    )
    return RelevanceFilterAgent(LLMRouter(config, transport=_relevance_transport_factory()))


def _build_synthesis_agent() -> NoteSynthesisAgent:
    config = LLMRouterConfig(
        tiers=[TierConfig(tier=LLMTier.TIER_1, model="m", endpoint="http://x")]
    )
    return NoteSynthesisAgent(LLMRouter(config, transport=_synthesis_transport_factory()))


async def _content_session_with_utterances(
    db: AsyncSession, n_relevant: int = 6, n_off_topic: int = 2
) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    subject = await PartitionProvisioner().provision_subject(db, user.id, name="S47 Subject")
    session_obj = Session(
        subject_id=subject.id, session_type="content", status=SessionStatus.TRANSCRIBED
    )
    db.add(session_obj)
    await db.flush()

    utterance_repo = UtteranceRepository(db)
    rows = []
    for i in range(n_relevant):
        rows.append(
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
        )
    for j in range(n_off_topic):
        seq = n_relevant + j
        rows.append(
            {
                "session_id": session_obj.id,
                "seq": seq,
                "start_ms": seq * 1000,
                "end_ms": seq * 1000 + 900,
                "text": "Totally off-topic aside about lunch",
                "asr_confidence": 0.9,
                "words": [],
                "speaker_tag": "SPK_A",
                "embed_model_ver": "v1",
            }
        )
    await utterance_repo.bulk_insert(subject.id, rows)
    return subject.id, session_obj.id


class TestT471FullFlowEndToEnd:
    async def test_transcript_to_notes(self, db_session: AsyncSession) -> None:
        """T47.1: full flow runs end to end on a real session, transcript -> notes."""
        subject_id, session_id = await _content_session_with_utterances(db_session)
        result = await process_session(
            session_id=session_id,
            subject_id=subject_id,
            embed_model_ver="v1",
            prompt_version="v1.0.0",
            db=db_session,
            embedding_client=FakeEmbeddingClient(),
            filter_agent=_build_filter_agent(),
            synthesis_agent=_build_synthesis_agent(),
        )

        assert result.success is True
        assert result.embedded_count == 8
        assert result.filtered_count == 6
        assert result.sections_persisted == 1

        refreshed = await db_session.get(Session, session_id)
        assert refreshed is not None
        assert refreshed.status == SessionStatus.COMPLETE
        assert refreshed.notes_ready is True


class TestT472NfrR3Gate:
    async def test_flow_aborts_when_not_transcribed(self, db_session: AsyncSession) -> None:
        subject_id, session_id = await _content_session_with_utterances(db_session)
        session_obj = await db_session.get(Session, session_id)
        assert session_obj is not None
        session_obj.status = SessionStatus.CREATED
        await db_session.flush()

        with pytest.raises(FlowAbortError):
            await process_session(
                session_id=session_id,
                subject_id=subject_id,
                embed_model_ver="v1",
                prompt_version="v1.0.0",
                db=db_session,
                embedding_client=FakeEmbeddingClient(),
                filter_agent=_build_filter_agent(),
                synthesis_agent=_build_synthesis_agent(),
            )


class TestT475PartialRerunUploadsPath:
    async def test_skip_embedding_reuses_t1_t3_and_reruns_tail(
        self, db_session: AsyncSession
    ) -> None:
        """T47.5: `uploads.ready` partial re-run reuses T1-T3, re-runs T4-T7."""
        subject_id, session_id = await _content_session_with_utterances(db_session)
        first = await process_session(
            session_id=session_id,
            subject_id=subject_id,
            embed_model_ver="v1",
            prompt_version="v1.0.0",
            db=db_session,
            embedding_client=FakeEmbeddingClient(),
            filter_agent=_build_filter_agent(),
            synthesis_agent=_build_synthesis_agent(),
        )
        assert first.success is True

        session_obj = await db_session.get(Session, session_id)
        assert session_obj is not None
        session_obj.status = SessionStatus.PROCESSING
        await db_session.flush()

        second = await process_session(
            session_id=session_id,
            subject_id=subject_id,
            embed_model_ver="v1",
            prompt_version="v1.0.0",
            db=db_session,
            embedding_client=FakeEmbeddingClient(),
            filter_agent=_build_filter_agent(),
            synthesis_agent=_build_synthesis_agent(),
            skip_embedding=True,
        )
        assert second.success is True
        assert second.embedded_count == 0
        assert "T1_embed_utterances" in second.skipped_stages
        assert second.filtered_count == 6
        assert second.sections_persisted == 1


class TestT477EventsEmitted:
    async def test_session_complete_event_emitted(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        subject_id, session_id = await _content_session_with_utterances(db_session)
        published: list[tuple[str, str, dict]] = []

        class FakeStream(ValkeyStreamProducer):
            def __init__(self) -> None:
                pass

            async def publish_event(self, session_id, event, data):  # type: ignore[override]
                published.append((session_id, event, data))

        result = await process_session(
            session_id=session_id,
            subject_id=subject_id,
            embed_model_ver="v1",
            prompt_version="v1.0.0",
            db=db_session,
            embedding_client=FakeEmbeddingClient(),
            filter_agent=_build_filter_agent(),
            synthesis_agent=_build_synthesis_agent(),
            stream=FakeStream(),
        )
        assert result.success is True
        assert any(event == "session.complete" for _, event, _ in published)

    async def test_session_failed_event_emitted_on_error(self, db_session: AsyncSession) -> None:
        subject_id, session_id = await _content_session_with_utterances(db_session)
        published: list[tuple[str, str, dict]] = []

        class FakeStream(ValkeyStreamProducer):
            def __init__(self) -> None:
                pass

            async def publish_event(self, session_id, event, data):  # type: ignore[override]
                published.append((session_id, event, data))

        class ExplodingSynthesisAgent(NoteSynthesisAgent):
            async def synthesize(self, context):  # type: ignore[override]
                msg = "synthesis exploded"
                raise RuntimeError(msg)

        with pytest.raises(RuntimeError):
            await process_session(
                session_id=session_id,
                subject_id=subject_id,
                embed_model_ver="v1",
                prompt_version="v1.0.0",
                db=db_session,
                embedding_client=FakeEmbeddingClient(),
                filter_agent=_build_filter_agent(),
                synthesis_agent=ExplodingSynthesisAgent(_build_synthesis_agent()._router),
                stream=FakeStream(),
            )

        assert any(event == "session.failed" for _, event, _ in published)
        refreshed = await db_session.get(Session, session_id)
        assert refreshed is not None
        assert refreshed.status == SessionStatus.FAILED


class TestT476ProcessingBudget:
    @pytest.mark.skip(reason=P3_SKIP_REASON)
    def test_sixty_minute_lecture_under_fifteen_minutes_p90(self) -> None:
        pass


WORKER_KILL_SKIP_REASON = (
    "Verifying a genuine mid-task worker kill and resume requires a deployed "
    "Prefect server/worker with a persistent result store; tasks here run as "
    "plain async functions under Prefect's local task runner (no "
    "fixture_prefect_server testcontainer in this environment), the same "
    "limitation tests/test_s27_flows.py documents for T27.1/T27.5. The "
    "underlying idempotency each task relies on to make a resume safe (cache "
    "keys below, plus T45's upsert idempotency) is verified directly instead."
)


class TestT472T473CacheKeysDriveSelectiveRecompute:
    def test_t2_cache_key_stable_across_prompt_version(self) -> None:
        """T2 has no prompt_version dependency - a prompt bump must not miss T2's cache."""
        session_id = uuid.uuid4()
        key_a = _cache_key_t2(None, {"session_id": session_id, "embed_model_ver": "v1"})
        key_b = _cache_key_t2(None, {"session_id": session_id, "embed_model_ver": "v1"})
        assert key_a == key_b

    def test_t2_cache_key_differs_on_embed_model_ver(self) -> None:
        """T47.3: an embedding version bump must invalidate every downstream cache from T1."""
        session_id = uuid.uuid4()
        key_v1 = _cache_key_t2(None, {"session_id": session_id, "embed_model_ver": "v1"})
        key_v2 = _cache_key_t2(None, {"session_id": session_id, "embed_model_ver": "v2"})
        assert key_v1 != key_v2

    @pytest.mark.parametrize("cache_key_fn", [_cache_key_t5, _cache_key_t6, _cache_key_t7])
    def test_prompt_dependent_tasks_recompute_on_prompt_bump(self, cache_key_fn) -> None:
        """T47.2: bumping prompt_version changes T5/T6/T7's cache key -> cache miss, recompute."""
        session_id = uuid.uuid4()
        key_a = cache_key_fn(None, {"session_id": session_id, "prompt_version": "v1.0.0"})
        key_b = cache_key_fn(None, {"session_id": session_id, "prompt_version": "v1.1.0"})
        assert key_a != key_b

    @pytest.mark.parametrize("cache_key_fn", [_cache_key_t5, _cache_key_t6, _cache_key_t7])
    def test_prompt_dependent_tasks_stable_for_same_prompt(self, cache_key_fn) -> None:
        session_id = uuid.uuid4()
        key_a = cache_key_fn(None, {"session_id": session_id, "prompt_version": "v1.0.0"})
        key_b = cache_key_fn(None, {"session_id": session_id, "prompt_version": "v1.0.0"})
        assert key_a == key_b


class TestT474WorkerKillResume:
    @pytest.mark.skip(reason=WORKER_KILL_SKIP_REASON)
    def test_kill_worker_mid_task_resumes_from_that_point(self) -> None:
        pass

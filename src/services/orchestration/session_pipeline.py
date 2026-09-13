"""S47 — full T1-T7 `process_session` flow wiring + partial re-run path.

Task numbering (as referenced by the S47 stage record):
    T1  embed_utterances    (S27, `src.ml.embedding.flows`)
    T2  segment_session     (S28, wraps `src.ml.clustering.segmentation`)
    T3  cluster_segments    (S30, `src.ml.clustering.tasks`)
    T4  route_session_type  (S47 dispatch)
    T5  filter_utterances   (S41/S43, A1 relevance filter + ensemble)
    T6  synthesize_notes    (S44, A2 note synthesis)
    T7  persist_notes       (S45, note persistence)

T4 note: the stage record calls this the "LangGraph T4 subgraph", but no
LangGraph runtime is used anywhere else in this codebase - S37-40's
multi-agent dispatch (`src.services.llm.router.LLMRouter`) is a plain
tiered-failover router, not a LangGraph graph. Introducing a new
graph-execution dependency for a single two-way dispatch (content vs.
non-content) would be pure ceremony, so T4 is a plain async dispatcher with
the same external contract LangGraph would have given it: `session_type`
in, a routing decision out. Only `session_type == "content"` is wired all
the way through T5-T7 here; `syllabus`/`mixed` routing to A6 is Block 9
(S50+) and is out of scope for S47 - those session types short-circuit
after T3 and complete without notes.

`src.ml.embedding.flows.process_session` (S27) is left untouched: it is the
minimal T1-only flow S27's own tests assert against. This module's
`process_session` is the full S47 pipeline used for real processing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from prefect import flow, get_run_logger, task
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.state_machine import SessionStateMachine
from src.db.models.session import Session, SessionStatus
from src.db.repositories.segment_repo import SegmentRepository
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.topic_repo import TopicRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.ml.clustering.schemas import ClusteringResult
from src.ml.clustering.segmentation import SegmentationResult, segment_session
from src.ml.clustering.tasks import cluster_segments
from src.ml.embedding.client import EmbeddingClient
from src.ml.embedding.flows import embed_utterances
from src.services.filtering.ensemble_voting import EnsembleVotingFilter
from src.services.filtering.relevance_filter import (
    RelevanceFilterAgent,
    UtteranceInput,
    decisions_to_flags,
)
from src.services.synthesis.note_persistence import (
    mark_notes_ready,
    persist_note_sections,
)
from src.services.synthesis.note_synthesis import (
    NoteSectionOutput,
    NoteSynthesisAgent,
    RelevantUtterance,
    SessionSynthesisContext,
)
from src.services.valkey_stream import ValkeyStreamProducer

CONTENT_SESSION_TYPE = "content"


class FlowAbortError(Exception):
    """Raised when the NFR-R3 entry gate rejects a session."""


@dataclass
class PipelineResult:
    session_id: uuid.UUID
    success: bool
    embedded_count: int = 0
    segments_created: int = 0
    topics_created: int = 0
    filtered_count: int = 0
    sections_persisted: int = 0
    session_type: str = CONTENT_SESSION_TYPE
    skipped_stages: list[str] = field(default_factory=list)
    error: str | None = None


def _cache_key_t2(context: object, parameters: dict[str, object]) -> str:
    return f"T2-{parameters['session_id']}-{parameters['embed_model_ver']}"


def _cache_key_t5(context: object, parameters: dict[str, object]) -> str:
    return f"T5-{parameters['session_id']}-{parameters['prompt_version']}"


def _cache_key_t6(context: object, parameters: dict[str, object]) -> str:
    return f"T6-{parameters['session_id']}-{parameters['prompt_version']}"


def _cache_key_t7(context: object, parameters: dict[str, object]) -> str:
    return f"T7-{parameters['session_id']}-{parameters['prompt_version']}"


@task(
    name="T2_segment_session",
    cache_key_fn=_cache_key_t2,
    cache_expiration=timedelta(hours=24),
    retries=1,
    retry_delay_seconds=30,
)
async def segment_session_task(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    embed_model_ver: str,
    db: AsyncSession,
) -> SegmentationResult:
    """T2: TextTiling-style segmentation over the session's embedded utterances."""
    utterance_repo = UtteranceRepository(db)
    segment_repo = SegmentRepository(db)

    utterances = await utterance_repo.get_by_session(subject_id, session_id)
    embedded = [u for u in utterances if u.embedding is not None]

    result = segment_session(
        embedded,  # type: ignore[arg-type]
        [list(u.embedding) for u in embedded],
        session_id=session_id,
    )
    await segment_repo.persist_segments(subject_id, session_id, result)
    return result


@dataclass
class RouteDecision:
    session_type: str
    proceed_to_filtering: bool


@task(name="T4_route_session_type")
async def route_session_type(session_obj: Session) -> RouteDecision:
    """T4: dispatch on `session_type`.

    Only `content` sessions proceed to A1 filtering / A2 synthesis in this
    stage; `syllabus`/`mixed` routing to A6 (S50+) is a later block.
    """
    session_type = session_obj.session_type
    return RouteDecision(
        session_type=session_type,
        proceed_to_filtering=(session_type == CONTENT_SESSION_TYPE),
    )


@dataclass
class FilterResult:
    filtered_count: int
    relevant: list[UtteranceInput]
    relevant_ids_by_seq: dict[int, str]


@task(
    name="T5_filter_utterances",
    cache_key_fn=_cache_key_t5,
    cache_expiration=timedelta(hours=24),
    retries=2,
    retry_delay_seconds=30,
)
async def filter_utterances_task(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    prompt_version: str,
    db: AsyncSession,
    filter_agent: RelevanceFilterAgent,
    ensemble: EnsembleVotingFilter | None = None,
) -> FilterResult:
    """T5: A1 relevance filtering, with optional S43 ensemble on ambiguous utterances."""
    utterance_repo = UtteranceRepository(db)
    topic_repo = TopicRepository(db)

    utterances = await utterance_repo.get_by_session(subject_id, session_id)
    if not utterances:
        return FilterResult(filtered_count=0, relevant=[], relevant_ids_by_seq={})

    topic_ids = {u.topic_id for u in utterances if u.topic_id is not None}
    labels_by_topic: dict[uuid.UUID, str] = {}
    for topic_id in topic_ids:
        topic = await topic_repo.get(subject_id, topic_id)
        if topic is not None:
            labels_by_topic[topic_id] = topic.label or (
                ", ".join(topic.keywords or []) or "unlabeled topic"
            )
    topic_label = next(iter(labels_by_topic.values()), "unlabeled topic")

    inputs = [
        UtteranceInput(seq=u.seq, text=u.text, outlier_score=u.outlier_score) for u in utterances
    ]
    decisions = await filter_agent.classify_session(topic_label, inputs)
    outlier_by_seq = {u.seq: u.outlier_score for u in utterances}

    if ensemble is not None:
        votes = await ensemble.classify_ambiguous(topic_label, inputs)
        decisions = [
            d
            if d.seq not in votes
            else d.model_copy(update={"is_relevant": votes[d.seq].is_relevant})
            for d in decisions
        ]

    flags = decisions_to_flags(decisions, outlier_by_seq)
    await utterance_repo.apply_relevance_flags(subject_id, session_id, flags)

    id_by_seq = {u.seq: str(u.id) for u in utterances}
    relevant = [inp for inp in inputs if flags[inp.seq][0]]
    relevant_ids_by_seq = {seq: id_by_seq[seq] for seq in id_by_seq if flags[seq][0]}
    return FilterResult(
        filtered_count=len(relevant), relevant=relevant, relevant_ids_by_seq=relevant_ids_by_seq
    )


@task(
    name="T6_synthesize_notes",
    cache_key_fn=_cache_key_t6,
    cache_expiration=timedelta(hours=24),
    retries=2,
    retry_delay_seconds=30,
)
async def synthesize_notes_task(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    prompt_version: str,
    db: AsyncSession,
    synthesis_agent: NoteSynthesisAgent,
    filter_result: FilterResult,
) -> list[NoteSectionOutput]:
    """T6: A2 full-context note synthesis over the utterances T5 kept."""
    if not filter_result.relevant:
        return []

    utterance_repo = UtteranceRepository(db)
    all_utterances = await utterance_repo.get_by_session(subject_id, session_id)
    by_seq = {u.seq: u for u in all_utterances}

    context = SessionSynthesisContext(
        session_id=str(session_id),
        utterances=[
            RelevantUtterance(
                id=filter_result.relevant_ids_by_seq[inp.seq],
                seq=inp.seq,
                text=by_seq[inp.seq].text,
            )
            for inp in filter_result.relevant
        ],
    )
    return await synthesis_agent.synthesize(context)


@task(
    name="T7_persist_notes",
    cache_key_fn=_cache_key_t7,
    cache_expiration=timedelta(hours=24),
    retries=1,
    retry_delay_seconds=30,
)
async def persist_notes_task(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    db: AsyncSession,
    session_obj: Session,
    sections: list[NoteSectionOutput],
) -> int:
    """T7: idempotent note persistence (S45), then flip `notes_ready`."""
    if not sections:
        return 0
    section_ids = await persist_note_sections(
        db=db,
        subject_id=subject_id,
        session_id=session_id,
        topic_id=None,
        sections=sections,
    )
    await mark_notes_ready(db, session_obj)
    return len(section_ids)


@flow(name="process_session_full", flow_run_name="process-full-{session_id}", retries=0)
async def process_session(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    embed_model_ver: str,
    prompt_version: str,
    db: AsyncSession,
    embedding_client: EmbeddingClient,
    filter_agent: RelevanceFilterAgent,
    synthesis_agent: NoteSynthesisAgent,
    ensemble: EnsembleVotingFilter | None = None,
    stream: ValkeyStreamProducer | None = None,
    skip_embedding: bool = False,
) -> PipelineResult:
    """S47: complete T1-T7 pipeline, transcript through persisted notes.

    `skip_embedding=True` is the `uploads.ready` partial re-run path: T1-T3
    are assumed already complete and cached from a prior run, so only the
    visual/filter/synth/persist tail (T4-T7) is re-run.
    """
    logger = get_run_logger()
    session_repo = SessionRepository(db)
    state_machine = SessionStateMachine()

    session_obj = await session_repo.get_or_raise(session_id)
    if session_obj.status != SessionStatus.TRANSCRIBED and not skip_embedding:
        msg = f"Session {session_id} status is '{session_obj.status}', expected 'transcribed'"
        raise FlowAbortError(msg)

    if session_obj.status != SessionStatus.PROCESSING:
        await state_machine.transition(session_obj, SessionStatus.PROCESSING, db)

    result = PipelineResult(session_id=session_id, success=False)

    try:
        if not skip_embedding:
            embed_result = await embed_utterances(
                session_id=session_id,
                subject_id=subject_id,
                embed_model_ver=embed_model_ver,
                db=db,
                client=embedding_client,
            )
            result.embedded_count = embed_result.embedded_count

            seg_result = await segment_session_task(
                session_id=session_id,
                subject_id=subject_id,
                embed_model_ver=embed_model_ver,
                db=db,
            )
            result.segments_created = seg_result.num_segments

            cluster_result: ClusteringResult = await cluster_segments(
                session_id=session_id, subject_id=subject_id, db=db
            )
            result.topics_created = cluster_result.topics_created
        else:
            result.skipped_stages = [
                "T1_embed_utterances",
                "T2_segment_session",
                "T3_cluster_segments",
            ]

        route = await route_session_type(session_obj)
        result.session_type = route.session_type

        if route.proceed_to_filtering:
            filter_result = await filter_utterances_task(
                session_id=session_id,
                subject_id=subject_id,
                prompt_version=prompt_version,
                db=db,
                filter_agent=filter_agent,
                ensemble=ensemble,
            )
            result.filtered_count = filter_result.filtered_count

            sections = await synthesize_notes_task(
                session_id=session_id,
                subject_id=subject_id,
                prompt_version=prompt_version,
                db=db,
                synthesis_agent=synthesis_agent,
                filter_result=filter_result,
            )

            result.sections_persisted = await persist_notes_task(
                session_id=session_id,
                subject_id=subject_id,
                db=db,
                session_obj=session_obj,
                sections=sections,
            )
        else:
            result.skipped_stages = [
                *result.skipped_stages,
                "T5_filter_utterances",
                "T6_synthesize_notes",
                "T7_persist_notes",
            ]

        if session_obj.status != SessionStatus.COMPLETE:
            await state_machine.transition(session_obj, SessionStatus.COMPLETE, db)

        result.success = True
        if stream is not None:
            await stream.publish_event(
                str(session_id),
                "session.complete",
                {
                    "session_id": str(session_id),
                    "subject_id": str(subject_id),
                    "sections_persisted": result.sections_persisted,
                },
            )
        return result  # noqa: TRY300
    except Exception as exc:
        logger.exception("process_session_full failed")
        await state_machine.transition(
            session_obj, SessionStatus.FAILED, db, reason=str(exc), stage="process_session_full"
        )
        if stream is not None:
            await stream.publish_event(
                str(session_id),
                "session.failed",
                {"session_id": str(session_id), "subject_id": str(subject_id), "error": str(exc)},
            )
        raise

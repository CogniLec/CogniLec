"""S27 — Prefect orchestration: `process_session` flow and task T1 (embed_utterances).

The `ml-pool`/`llm-pool` work-pool topology (ADR-002) and the
`session.transcribed` event trigger (ADR-003) are configured at deployment
time (`prefect.yaml` / `prefect deployment` CLI, see spec §6.1/§6.4) - this
module holds the flow/task code that gets deployed onto those pools.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from prefect import flow, get_run_logger, task
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.state_machine import SessionStateMachine
from src.db.models.session import SessionStatus
from src.db.models.utterance import Utterance
from src.db.repositories.session_repo import SessionRepository
from src.db.repositories.utterance_repo import UtteranceRepository
from src.ml.embedding.client import EmbeddingClient
from src.ml.embedding.pipeline import embed_session_windowed
from src.services.valkey_stream import ValkeyStreamProducer


class FlowAbortError(Exception):
    """Raised when the NFR-R3 entry gate rejects a session (S27 §5.2)."""


@dataclass
class EmbeddingResult:
    session_id: uuid.UUID
    embedded_count: int
    embed_model_ver: str


@dataclass
class ProcessSessionResult:
    success: bool
    embedding_result: EmbeddingResult | None = None
    error: str | None = None


def _cache_key_t1(context: object, parameters: dict[str, object]) -> str:
    return f"T1-{parameters['session_id']}-{parameters['embed_model_ver']}"


@task(
    name="T1_embed_utterances",
    cache_key_fn=_cache_key_t1,
    cache_expiration=timedelta(hours=24),
    retries=2,
    retry_delay_seconds=30,
)
async def embed_utterances(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    embed_model_ver: str,
    db: AsyncSession,
    client: EmbeddingClient,
    window_size: int = 5,
) -> EmbeddingResult:
    """T1: embed all utterances of a session using S26 context windows.

    Idempotent: `UtteranceRepository.update_embedding` is a plain UPDATE on
    the primary key, so re-running with the same `(session_id,
    embed_model_ver)` overwrites with an identical result (NFR-R6).
    """
    repo = UtteranceRepository(db)
    rows = await repo.get_by_embed_version(subject_id, embed_model_ver) or []
    session_utterances = [
        Utterance(
            id=uuid.UUID(str(r["id"])) if not isinstance(r["id"], uuid.UUID) else r["id"],
            subject_id=subject_id,
            session_id=session_id,
            seq=r["seq"],
            start_ms=r["start_ms"],
            end_ms=r["end_ms"],
            text=r["text"],
            embed_model_ver=embed_model_ver,
        )
        for r in rows
        if str(r["session_id"]) == str(session_id)
    ]
    session_utterances.sort(key=lambda u: u.seq)

    results = await embed_session_windowed(
        session_utterances,  # type: ignore[arg-type]
        client,
        W=window_size,
        task_mode="clustering",
    )
    for res in results:
        await repo.update_embedding(subject_id, res.utterance_id, res.embedding, embed_model_ver)

    return EmbeddingResult(
        session_id=session_id, embedded_count=len(results), embed_model_ver=embed_model_ver
    )


@flow(name="process_session", flow_run_name="process-{session_id}", retries=0)
async def process_session(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    embed_model_ver: str,
    db: AsyncSession,
    client: EmbeddingClient,
    stream: ValkeyStreamProducer | None = None,
    window_size: int = 5,
) -> ProcessSessionResult:
    """Main session processing flow: NFR-R3 gate, then T1 embedding.

    Segmentation (T2) and clustering (T3) are wired in by S28/S30; this flow
    intentionally stops after T1 per the S27 scope.
    """
    logger = get_run_logger()
    session_repo = SessionRepository(db)
    state_machine = SessionStateMachine()

    session_obj = await session_repo.get_or_raise(session_id)
    if session_obj.status != SessionStatus.TRANSCRIBED:
        logger.warning(
            "flow.nfr_r3_gate_failed session_id=%s status=%s", session_id, session_obj.status
        )
        msg = f"Session {session_id} status is '{session_obj.status}', expected 'transcribed'"
        raise FlowAbortError(msg)

    await state_machine.transition(session_obj, SessionStatus.PROCESSING, db)

    try:
        embedding_result = await embed_utterances(
            session_id=session_id,
            subject_id=subject_id,
            embed_model_ver=embed_model_ver,
            db=db,
            client=client,
            window_size=window_size,
        )
        await state_machine.transition(session_obj, SessionStatus.COMPLETE, db)
        return ProcessSessionResult(success=True, embedding_result=embedding_result)
    except Exception as exc:
        logger.exception("Flow failed")
        await state_machine.transition(
            session_obj, SessionStatus.FAILED, db, reason=str(exc), stage="T1_embed_utterances"
        )
        if stream is not None:
            await stream.publish_event(
                str(session_id),
                "session.failed",
                {"session_id": str(session_id), "subject_id": str(subject_id), "error": str(exc)},
            )
        raise

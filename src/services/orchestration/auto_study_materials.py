"""Auto-triggers S47 note synthesis + S58 flashcard generation once a
session finishes transcribing.

Previously nothing in the pipeline called this automatically -- see the
docstring on src/api/routes/study.py's seed_flashcard, which existed only
as a manual stopgap "until that generation trigger exists." This module
is that trigger, invoked from src/workers/asr_worker.py right after a
session is finalized (RECORDING -> TRANSCRIBED).

Deliberately best-effort: any failure here is logged and swallowed rather
than raised, since this runs inline in the ASR worker's per-message loop
-- one subject's note-synthesis/flashcard-generation failure (e.g. the
LLM router being temporarily unreachable) must not crash transcription
for every other session the worker is processing.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import get_settings
from src.db.models.flashcard import Flashcard
from src.db.models.topic import Topic
from src.ml.embedding.client import EmbeddingClient
from src.services.filtering.relevance_filter import RelevanceFilterAgent
from src.services.llm.router import LLMRouter, LLMRouterConfig, LLMTier, TierConfig
from src.services.orchestration.session_pipeline import process_session
from src.services.study.flashcards import FlashcardGenerationError, FlashcardGenerator
from src.services.study.fsrs_scheduler import new_card_fields
from src.services.synthesis.note_synthesis import NoteSynthesisAgent

logger = logging.getLogger(__name__)

FLASHCARDS_PER_TOPIC = 5
PROMPT_VERSION = "v1.0.0"


def _build_llm_router() -> LLMRouter:
    settings = get_settings()
    # LiteLLM's own /chat/completions (not /v1/chat/completions) --
    # confirmed live against the actual deployed litellm container
    # (docs/gaps.md #29-#31). "tier_1_local" matches config/litellm.yaml's
    # model_name for the vLLM tier.
    tier = TierConfig(
        tier=LLMTier.TIER_1,
        model="tier_1_local",
        endpoint=settings.LITELLM_BASE_URL,
        # Must be >= config/litellm.yaml's tier_1_local timeout (240s) --
        # confirmed live: a real S41 relevance-filter batch on a 45s clip
        # exceeded a 60s timeout on Machine B's small quantized model, so
        # a tighter client-side timeout here would just cut the request
        # off before LiteLLM's own (now-raised) timeout ever got a chance.
        # Raised again to 240s once guided_json (constrained decoding) was
        # enabled: measured live, it adds real latency (67-110s for an
        # 8-utterance batch even with a warm FSM cache).
        timeout_s=240,
    )
    return LLMRouter(LLMRouterConfig(tiers=[tier]))


def _topic_label(topic: Topic) -> str:
    return topic.label or (", ".join(topic.keywords or []) or "unlabeled topic")


async def generate_study_materials(
    session_id: uuid.UUID,
    subject_id: uuid.UUID,
    db: AsyncSession,
) -> int:
    """Runs process_session (embeddings -> segments -> topics -> notes),
    then generates and persists real flashcards per topic. Returns the
    number of flashcards created (0 on any failure or if there was
    nothing to synthesize)."""
    settings = get_settings()
    router = _build_llm_router()
    embedding_client = EmbeddingClient(
        tei_base_url=settings.TEI_BASE_URL,
        # CPU, not cuda:{EMBEDDING_CUDA_DEVICE} -- confirmed live:
        # TEI (the primary path, real GPU-backed service on Machine C) is
        # what's supposed to own the embedding GPU. This local fallback is
        # meant to be a rare degraded path, not a second consumer
        # contending for the same scarce card -- on this single-GPU dev
        # host it hit CUDA OOM (asr-worker's own GPU already ~2.8GB/3.6GB
        # used) the moment a real, larger batch fell back to it.
        local_device="cpu",
    )
    filter_agent = RelevanceFilterAgent(router)
    synthesis_agent = NoteSynthesisAgent(router)

    try:
        result = await process_session(
            session_id=session_id,
            subject_id=subject_id,
            embed_model_ver=settings.EMBED_MODEL_VER,
            prompt_version=PROMPT_VERSION,
            db=db,
            embedding_client=embedding_client,
            filter_agent=filter_agent,
            synthesis_agent=synthesis_agent,
            router=router,
        )
    except Exception:
        logger.exception(
            "process_session failed during auto study-material generation",
            extra={"session_id": str(session_id)},
        )
        return 0

    # process_session's own state-machine transition (-> COMPLETE) and note
    # persistence are not durable until committed -- process_session
    # itself never commits (same convention as _finalize_session in
    # asr_worker.py, whose own docstring says the caller must commit).
    # Confirmed live: without this, the flow logged "Completed" and
    # genuinely produced notes/topics in this session's transaction, but
    # none of it was ever actually written -- the session stayed stuck at
    # "transcribed" forever and no flashcards could reference topics that
    # were rolled back before this function returned.
    await db.commit()

    if result.sections_persisted == 0:
        logger.info(
            "no notes persisted; skipping flashcard generation",
            extra={"session_id": str(session_id)},
        )
        return 0

    topics_result = await db.execute(select(Topic).where(Topic.subject_id == subject_id))
    topics = list(topics_result.scalars().all())

    generator = FlashcardGenerator(router)
    created = 0
    for topic in topics:
        topic_label = _topic_label(topic)
        try:
            generated = await generator.generate_for_topic(
                db, subject_id, topic_label, FLASHCARDS_PER_TOPIC
            )
        except FlashcardGenerationError:
            logger.exception(
                "flashcard generation failed for topic",
                extra={"session_id": str(session_id), "topic": topic_label},
            )
            continue

        for card in generated:
            flashcard = Flashcard(
                subject_id=subject_id,
                topic_label=topic_label,
                front=card.front,
                back=card.back,
                **new_card_fields(),
            )
            db.add(flashcard)
            created += 1

    if created:
        await db.commit()
    logger.info(
        "auto study-material generation complete",
        extra={"session_id": str(session_id), "flashcards_created": created},
    )
    return created

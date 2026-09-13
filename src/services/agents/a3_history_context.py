"""S56 — A3 history context: cross-session relationship links.

A3 identifies typed relationships (`builds_on`, `revisits`, `contradicts`,
`prerequisite_for`) between the current session's content and prior stored
content, retrieved through the shared, stateless `RetrievalService` (S55)
over a read-only DB connection (T56.2 - see
`src/services/retrieval/readonly_session.py`).

A3 never calls A5 and never consumes A5's output (T56.3, AC-15): this
module imports nothing from `src.services.agents.a5_question_gen`, and
`A3HistoryContextAgent` takes no A5 client/handle anywhere in its
constructor or methods - a caller cannot wire one in even by mistake. The
resulting links are returned to the caller as plain dataclasses; persisting
them (a write) is the orchestrator's job via a normal, write-capable
session and repository, deliberately kept out of this module so the agent
itself never needs write access.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.note_link import NoteLinkType
from src.services.llm.router import LLMRouter
from src.services.retrieval.reranker import RerankerClient
from src.services.retrieval.retrieval_service import retrieve

LINK_TYPES = NoteLinkType.ALL


@dataclass(frozen=True)
class PriorSession:
    session_id: uuid.UUID
    summary_text: str


class LinkDecision(BaseModel):
    to_session_id: str
    link_type: str = Field(pattern="^(builds_on|revisits|contradicts|prerequisite_for)$")
    rationale: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)


class A3HistoryContextError(Exception):
    """Raised when A3's history-context response can't be parsed."""


def build_prompt(
    current_session_text: str, prior_sessions: list[PriorSession]
) -> list[dict[str, str]]:
    system = (
        "You are A3, identifying relationships between the current lecture "
        "session and the student's prior sessions in this subject. For each "
        "prior session that has a genuine relationship to the current one, "
        'emit {"to_session_id": str, "link_type": one of "builds_on"|'
        '"revisits"|"contradicts"|"prerequisite_for", "rationale": short '
        'string, "confidence": 0-1}. Only include prior sessions with a real '
        "relationship - omit unrelated ones entirely. Respond with a JSON "
        "array (possibly empty)."
    )
    user = json.dumps(
        {
            "current_session": current_session_text,
            "prior_sessions": [
                {"session_id": str(p.session_id), "text": p.summary_text} for p in prior_sessions
            ],
        }
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_links(raw: str, valid_session_ids: set[str]) -> list[LinkDecision]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"non-JSON A3 history-context response: {exc}"
        raise A3HistoryContextError(msg) from exc
    if not isinstance(payload, list):
        msg = "A3 history-context response must be a JSON array"
        raise A3HistoryContextError(msg)

    decisions: list[LinkDecision] = []
    try:
        for item in payload:
            decision = LinkDecision.model_validate(item)
            if decision.to_session_id not in valid_session_ids:
                continue
            decisions.append(decision)
    except ValidationError as exc:
        msg = f"malformed A3 link decision: {exc}"
        raise A3HistoryContextError(msg) from exc
    return decisions


class A3HistoryContextAgent:
    """A3 — identifies cross-session relationships via RetrievalService (read-only)."""

    AGENT_ID = "A3_HISTORY_CONTEXT"

    def __init__(self, router: LLMRouter, prompt_version: str = "v1.0.0") -> None:
        self._router = router
        self._prompt_version = prompt_version

    async def identify_relationships(
        self,
        readonly_db: AsyncSession,
        subject_id: uuid.UUID,
        current_session_text: str,
        current_session_id: uuid.UUID | None = None,
        reranker: RerankerClient | None = None,
    ) -> list[LinkDecision]:
        """Retrieve prior session context and identify typed relationships.

        First session in a subject (no history) -> the retrieval call
        returns no prior sessions, and this returns `[]` without ever
        calling the LLM (T56.5) - there is nothing to compare against.
        """
        result = await retrieve(
            readonly_db,
            subject_id=subject_id,
            query=current_session_text,
            query_embedding=None,
            reranker=reranker,
            merge_hierarchy=False,
        )
        prior_by_session: dict[uuid.UUID, list[str]] = {}
        for item in result.items:
            sid = item.result.session_id
            if sid is None or sid == current_session_id:
                continue
            prior_by_session.setdefault(sid, []).append(item.result.text)

        if not prior_by_session:
            return []

        prior_sessions = [
            PriorSession(session_id=sid, summary_text=" ".join(texts[:5]))
            for sid, texts in prior_by_session.items()
        ]

        messages = build_prompt(current_session_text, prior_sessions)
        response = await self._router.complete(
            messages, agent_id=self.AGENT_ID, prompt_version=self._prompt_version
        )
        if response.failed:
            msg = f"A3 history-context router exhausted: {response.failure_reason}"
            raise A3HistoryContextError(msg)

        valid_ids = {str(p.session_id) for p in prior_sessions}
        return parse_links(response.content, valid_ids)

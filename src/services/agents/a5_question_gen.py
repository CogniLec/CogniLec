"""S57 — A5 question generation with a consensus answerability check.

A5 generates questions/quizzes/mock tests over topics retrieved through the
shared, stateless `RetrievalService` (S55) via a read-only DB connection
(T57.4, mirrors A3's read-only access in S56). Every generated question is
then checked for answerability by a *different* model attempting to answer
it using only the stored notes (never the question's own generation
context) - a question that model can't answer is discarded (T57.2/T57.3).

A5 never calls A3 and never reads A3's output (T57.5, AC-15): this module
does not import `src.services.agents.a3_history_context`, and neither
`QuestionGenerator` nor `AnswerabilityChecker` accepts an A3 handle.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.llm.router import LLMRouter
from src.services.retrieval.reranker import RerankerClient
from src.services.retrieval.retrieval_service import retrieve

VALID_QUESTION_TYPES = ("mcq", "short_answer", "essay", "true_false")
VALID_DIFFICULTIES = ("easy", "medium", "hard")


class GeneratedQuestion(BaseModel):
    question: str = Field(min_length=10, max_length=2000)
    question_type: str = Field(pattern="^(mcq|short_answer|essay|true_false)$")
    options: list[str] | None = Field(default=None, min_length=2, max_length=6)
    correct_answer: str = Field(min_length=1)
    explanation: str = Field(min_length=10, max_length=1000)
    difficulty: str = Field(pattern="^(easy|medium|hard)$")
    topic_tags: list[str] = Field(min_length=1, max_length=5)


class A5GenerationError(Exception):
    """Raised when A5's question-generation response can't be parsed."""


@dataclass(frozen=True)
class AssessmentConfig:
    topics: list[str]
    count: int
    difficulty: str = "medium"


def build_generation_prompt(config: AssessmentConfig, notes_context: str) -> list[dict[str, str]]:
    system = (
        "You are A5, generating an assessment strictly from the student's "
        "own stored notes provided below. Generate exactly the requested "
        "count of questions, covering the requested topics, at the "
        "requested difficulty. Respond with a JSON array of objects: "
        '{"question": str, "question_type": one of "mcq"|"short_answer"|'
        '"essay"|"true_false", "options": array or null, "correct_answer": '
        'str, "explanation": str, "difficulty": "easy"|"medium"|"hard", '
        '"topic_tags": array of str}. Every question must be answerable '
        "from the given notes alone."
    )
    user = json.dumps(
        {
            "topics": config.topics,
            "count": config.count,
            "difficulty": config.difficulty,
            "notes_context": notes_context,
        }
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_generated_questions(raw: str) -> list[GeneratedQuestion]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"non-JSON A5 response: {exc}"
        raise A5GenerationError(msg) from exc
    if not isinstance(payload, list):
        msg = "A5 response must be a JSON array"
        raise A5GenerationError(msg)
    try:
        return [GeneratedQuestion.model_validate(item) for item in payload]
    except ValidationError as exc:
        msg = f"malformed A5 question: {exc}"
        raise A5GenerationError(msg) from exc


class QuestionGenerator:
    """A5 — generates questions from retrieved notes (read-only)."""

    AGENT_ID = "A5_QUESTION_GEN"

    def __init__(self, router: LLMRouter, prompt_version: str = "v1.0.0") -> None:
        self._router = router
        self._prompt_version = prompt_version

    async def generate(
        self,
        readonly_db: AsyncSession,
        subject_id: uuid.UUID,
        config: AssessmentConfig,
        reranker: RerankerClient | None = None,
    ) -> list[GeneratedQuestion]:
        query = " ".join(config.topics)
        result = await retrieve(
            readonly_db,
            subject_id=subject_id,
            query=query,
            query_embedding=None,
            reranker=reranker,
            limit=max(config.count * 3, 10),
            merge_hierarchy=False,
        )
        notes_context = "\n".join(item.result.text for item in result.items)

        messages = build_generation_prompt(config, notes_context)
        response = await self._router.complete(
            messages, agent_id=self.AGENT_ID, prompt_version=self._prompt_version
        )
        if response.failed:
            msg = f"A5 router exhausted: {response.failure_reason}"
            raise A5GenerationError(msg)
        return parse_generated_questions(response.content)


class AnswerVerdict(BaseModel):
    answerable: bool
    rationale: str = Field(min_length=1, max_length=300)


def build_answerability_prompt(
    question: GeneratedQuestion, notes_context: str
) -> list[dict[str, str]]:
    system = (
        "You are an independent answer-checking model. Using ONLY the "
        "notes provided (never any outside knowledge), attempt to answer "
        "the given question. If you cannot determine a confident answer "
        "from the notes alone, mark it unanswerable. Respond with JSON: "
        '{"answerable": bool, "rationale": short string}.'
    )
    user = json.dumps({"question": question.question, "notes_context": notes_context})
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class AnswerabilityChecker:
    """Consensus answerability check: a *different* model attempts each question."""

    AGENT_ID = "A5_ANSWERABILITY_CHECK"

    def __init__(self, router: LLMRouter, prompt_version: str = "v1.0.0") -> None:
        self._router = router
        self._prompt_version = prompt_version

    async def check(self, question: GeneratedQuestion, notes_context: str) -> AnswerVerdict:
        messages = build_answerability_prompt(question, notes_context)
        response = await self._router.complete(
            messages, agent_id=self.AGENT_ID, prompt_version=self._prompt_version
        )
        if response.failed:
            # Fail closed: an unreachable checker means the question can't
            # be confirmed answerable, so it must be discarded, not kept.
            return AnswerVerdict(answerable=False, rationale="answerability check unavailable")
        try:
            payload = json.loads(response.content)
            return AnswerVerdict.model_validate(payload)
        except (json.JSONDecodeError, ValidationError):
            return AnswerVerdict(answerable=False, rationale="malformed answerability response")

    async def filter_answerable(
        self, questions: list[GeneratedQuestion], notes_context: str
    ) -> tuple[list[GeneratedQuestion], list[tuple[GeneratedQuestion, AnswerVerdict]]]:
        kept: list[GeneratedQuestion] = []
        discarded: list[tuple[GeneratedQuestion, AnswerVerdict]] = []
        for q in questions:
            verdict = await self.check(q, notes_context)
            if verdict.answerable:
                kept.append(q)
            else:
                discarded.append((q, verdict))
        return kept, discarded

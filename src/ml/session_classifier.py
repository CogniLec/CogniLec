"""S35 — Session type classification (content/syllabus/mixed) with ensemble
voting and segment-level routing for mixed sessions.

Misclassification is high-consequence (v2.0 §4.1): routing syllabus content
to the content DB loses structure, routing content to the syllabus DB
pollutes it. Ensemble disagreement is flagged for review rather than guessed.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

log = logging.getLogger(__name__)

SessionType = str  # "content" | "syllabus" | "mixed"

SYLLABUS_KEYWORDS = [
    "syllabus",
    "grading",
    "assessment",
    "schedule",
    "office hours",
    "prerequisites",
    "textbook",
    "curriculum",
]

DENSITY_HIGH_DEFAULT = 0.02
DENSITY_LOW_DEFAULT = 0.005


class ClassificationVote(BaseModel):
    component: str
    prediction: SessionType
    confidence: float


class SessionClassification(BaseModel):
    session_id: uuid.UUID
    votes: list[ClassificationVote]
    final_type: SessionType
    confidence: float
    method: str
    details: dict[str, Any]
    classified_at: datetime


class SegmentRoute(BaseModel):
    segment_id: uuid.UUID
    route_target: str
    classification: str
    confidence: float


class SessionRoutePlan(BaseModel):
    session_id: uuid.UUID
    session_type: SessionType
    segment_routes: list[SegmentRoute]
    created_at: datetime


LLMClassifyFn = Callable[[str], Awaitable[tuple[SessionType, float]]]
"""Given transcript text, returns (prediction, confidence). May raise."""


def classify_rule_keyword(
    text: str,
    density_high: float = DENSITY_HIGH_DEFAULT,
    density_low: float = DENSITY_LOW_DEFAULT,
) -> ClassificationVote:
    words = re.findall(r"\w+", text.lower())
    total_words = max(len(words), 1)
    lowered = text.lower()
    keyword_hits = sum(lowered.count(kw) for kw in SYLLABUS_KEYWORDS)
    density = keyword_hits / total_words

    if density > density_high:
        prediction, confidence = "syllabus", min(1.0, density / density_high)
    elif density < density_low:
        prediction, confidence = "content", 1.0 - (density / density_low if density_low else 0.0)
    else:
        prediction, confidence = "mixed", 0.5

    return ClassificationVote(
        component="rule_keyword", prediction=prediction, confidence=confidence
    )


_LIST_MARKER_RE = re.compile(
    r"\b(first(?:ly)?|second(?:ly)?|third(?:ly)?|finally)\b", re.IGNORECASE
)
_DATE_RE = re.compile(
    r"\b(due|deadline|by\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"|\d{1,2}/\d{1,2}|week\s+\d+)\b",
    re.IGNORECASE,
)


def classify_rule_structure(utterance_texts: list[str]) -> ClassificationVote:
    """Structure heuristics: list markers, date/deadline mentions, short utterances."""
    if not utterance_texts:
        return ClassificationVote(component="rule_structure", prediction="mixed", confidence=0.0)

    joined = " ".join(utterance_texts)
    list_hits = len(_LIST_MARKER_RE.findall(joined))
    date_hits = len(_DATE_RE.findall(joined))
    short_count = sum(1 for t in utterance_texts if len(t.split()) < 8)
    short_ratio = short_count / len(utterance_texts)

    syllabus_score = (list_hits * 0.15) + (date_hits * 0.2) + (short_ratio * 0.5)

    if syllabus_score > 0.6:
        prediction, confidence = "syllabus", min(1.0, syllabus_score)
    elif syllabus_score < 0.2:
        prediction, confidence = "content", 1.0 - syllabus_score
    else:
        prediction, confidence = "mixed", 0.5

    return ClassificationVote(
        component="rule_structure", prediction=prediction, confidence=confidence
    )


async def classify_llm(
    text: str,
    llm_classify_fn: LLMClassifyFn | None,
) -> ClassificationVote | None:
    """LLM classification component. Returns None on failure (§6.5 fallback:
    caller drops to rule-based only, method='rule_only')."""
    if llm_classify_fn is None:
        return None
    try:
        prediction, confidence = await llm_classify_fn(text)
        return ClassificationVote(component="llm", prediction=prediction, confidence=confidence)
    except Exception:
        log.warning("classification_fallback", exc_info=True)
        return None


def vote_ensemble(votes: list[ClassificationVote]) -> tuple[SessionType, float, bool]:
    """§6.1 voting logic. Returns (final_type, confidence, disagreement_flag)."""
    if not votes:
        return "content", 0.0, True

    predictions = [v.prediction for v in votes]
    counts: dict[str, int] = {}
    for p in predictions:
        counts[p] = counts.get(p, 0) + 1

    max_count = max(counts.values())
    winners = [p for p, c in counts.items() if c == max_count]

    if len(winners) == 1 and max_count > len(votes) / 2:
        winner = winners[0]
        avg_confidence = sum(v.confidence for v in votes if v.prediction == winner) / max_count
        return winner, avg_confidence, False

    if len(winners) == 1 and max_count == len(votes):
        return winners[0], sum(v.confidence for v in votes) / len(votes), False

    log.warning("classification_disagreement", extra={"votes": [v.model_dump() for v in votes]})
    return "mixed", 0.0, True


async def classify_session(
    session_id: uuid.UUID,
    transcript_text: str,
    utterance_texts: list[str],
    operator_session_type: SessionType | None = None,
    llm_classify_fn: LLMClassifyFn | None = None,
    llm_enabled: bool = True,
    rule_keyword_enabled: bool = True,
    rule_structure_enabled: bool = True,
) -> SessionClassification:
    """§6.1: operator override takes precedence; otherwise ensemble vote."""
    now = datetime.now(UTC)

    if operator_session_type is not None and operator_session_type != "content":
        return SessionClassification(
            session_id=session_id,
            votes=[],
            final_type=operator_session_type,
            confidence=1.0,
            method="operator_override",
            details={"operator_session_type": operator_session_type},
            classified_at=now,
        )

    votes: list[ClassificationVote] = []
    if llm_enabled:
        llm_vote = await classify_llm(transcript_text, llm_classify_fn)
        if llm_vote is not None:
            votes.append(llm_vote)
    if rule_keyword_enabled:
        votes.append(classify_rule_keyword(transcript_text))
    if rule_structure_enabled:
        votes.append(classify_rule_structure(utterance_texts))

    if not votes:
        return SessionClassification(
            session_id=session_id,
            votes=[],
            final_type="content",
            confidence=0.0,
            method="rule_only",
            details={"error": "all_classifiers_failed"},
            classified_at=now,
        )

    final_type, confidence, disagreement = vote_ensemble(votes)
    method = "ensemble"
    if llm_enabled and not any(v.component == "llm" for v in votes):
        method = "rule_only"

    return SessionClassification(
        session_id=session_id,
        votes=votes,
        final_type=final_type,
        confidence=confidence,
        method=method,
        details={
            "vote_counts": {v.component: v.prediction for v in votes},
            "flagged_for_review": disagreement,
        },
        classified_at=now,
    )


def classify_segment_text(text: str) -> ClassificationVote:
    """Reuses the rule-keyword classifier as the per-segment classification
    for routing purposes (§6.2). Segment texts are short; the keyword
    density heuristic is cheap and doesn't require an LLM round-trip per
    segment."""
    return classify_rule_keyword(text)


def route_segments(
    session_id: uuid.UUID,
    session_type: SessionType,
    segment_texts: dict[uuid.UUID, str],
) -> SessionRoutePlan:
    """§6.2: route each segment individually. For non-mixed sessions, every
    segment routes to the session's single target. For mixed sessions, each
    segment is classified independently."""
    routes: list[SegmentRoute] = []

    if session_type != "mixed":
        target = "db_3" if session_type == "syllabus" else "db_2"
        for segment_id in segment_texts:
            routes.append(
                SegmentRoute(
                    segment_id=segment_id,
                    route_target=target,
                    classification=session_type,
                    confidence=1.0,
                )
            )
    else:
        for segment_id, text in segment_texts.items():
            vote = classify_segment_text(text)
            classification = "syllabus" if vote.prediction == "syllabus" else "content"
            if vote.prediction == "mixed":
                classification = "content"
            target = "db_3" if classification == "syllabus" else "db_2"
            routes.append(
                SegmentRoute(
                    segment_id=segment_id,
                    route_target=target,
                    classification=classification,
                    confidence=vote.confidence,
                )
            )

    return SessionRoutePlan(
        session_id=session_id,
        session_type=session_type,
        segment_routes=routes,
        created_at=datetime.now(UTC),
    )

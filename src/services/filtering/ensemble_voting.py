"""S43 - A1 ensemble voting for ambiguous-outlier-score utterances.

For utterances whose outlier score falls in a configurable "ambiguity band"
(~15% of traffic per the spec), 2-3 models vote independently. A split vote
retains the utterance and flags it for human review - it never discards on
disagreement, honouring A1's asymmetric cost (S42).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.services.filtering.relevance_filter import (
    RelevanceDecision,
    RelevanceFilterAgent,
    UtteranceInput,
)


@dataclass(frozen=True)
class AmbiguityBand:
    """Utterances with outlier_score in [low, high] are ambiguous."""

    low: float = 0.4
    high: float = 0.6

    def contains(self, outlier_score: float | None) -> bool:
        if outlier_score is None:
            return False
        return self.low <= outlier_score <= self.high


@dataclass(frozen=True)
class VoteResult:
    seq: int
    is_relevant: bool
    needs_review: bool
    votes: tuple[bool, ...]


def is_ambiguous(utterance: UtteranceInput, band: AmbiguityBand) -> bool:
    return band.contains(utterance.outlier_score)


def vote(votes: list[bool]) -> tuple[bool, bool]:
    """Return (is_relevant, needs_review) from independent keep/discard votes.

    A tie (split vote) always resolves to KEEP + review flag. With an odd
    number of voters there is no true tie, but this still guards a
    configuration where two voters agree and treats a 1-1 sub-count on a
    3-way vote consistently.
    """
    keep_votes = sum(1 for v in votes if v)
    discard_votes = len(votes) - keep_votes
    if keep_votes == discard_votes:
        return True, True
    return keep_votes > discard_votes, False


class EnsembleVotingFilter:
    """Wraps N independent `RelevanceFilterAgent` instances (distinct models/tiers)."""

    def __init__(
        self,
        agents: list[RelevanceFilterAgent],
        band: AmbiguityBand = AmbiguityBand(),
    ) -> None:
        if not agents:
            msg = "EnsembleVotingFilter requires at least one agent"
            raise ValueError(msg)
        self._agents = agents
        self._band = band

    @property
    def band(self) -> AmbiguityBand:
        return self._band

    async def classify_ambiguous(
        self, topic_label: str, utterances: list[UtteranceInput]
    ) -> dict[int, VoteResult]:
        """Vote only on utterances inside the ambiguity band.

        Each agent classifies the same full batch independently (T43.4 - no
        agent sees another's output); votes are combined per-utterance.
        A `band` with `low > high` (empty range) makes every utterance
        non-ambiguous, degenerating to zero ensemble calls (T43.3).
        """
        ambiguous = [u for u in utterances if is_ambiguous(u, self._band)]
        if not ambiguous:
            return {}

        per_agent_decisions: list[list[RelevanceDecision]] = []
        for agent in self._agents:
            per_agent_decisions.append(await agent.classify_session(topic_label, ambiguous))

        results: dict[int, VoteResult] = {}
        for u in ambiguous:
            votes = [
                next(d.is_relevant for d in decisions if d.seq == u.seq)
                for decisions in per_agent_decisions
            ]
            is_relevant, needs_review = vote(votes)
            results[u.seq] = VoteResult(
                seq=u.seq, is_relevant=is_relevant, needs_review=needs_review, votes=tuple(votes)
            )
        return results

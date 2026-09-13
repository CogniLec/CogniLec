"""S26 — context-window construction over an ordered utterance stream."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


class _HasSeqAndText(Protocol):
    id: uuid.UUID
    seq: int
    text: str


@dataclass
class WindowedUtterance:
    """An utterance with its context window assembled (S26 §5.2)."""

    utterance_id: uuid.UUID
    seq: int
    window_text: str
    window_size_actual: int
    individual_text: str


def build_windows(
    utterances: list[_HasSeqAndText],
    W: int = 5,  # noqa: N803 - matches the spec's contract (S26 §5.2)
    stride: int = 1,
) -> list[WindowedUtterance]:
    """Build overlapping context windows of W preceding utterances plus current.

    At transcript start (fewer than W predecessors) the window shrinks.
    W=0 degenerates to isolated embedding (each utterance alone).
    `stride` is accepted for interface completeness but every utterance still
    gets its own window (S26 requires per-utterance embeddings for
    downstream segmentation, so windows are not skipped between strides).
    """
    if not utterances:
        return []

    windows: list[WindowedUtterance] = []
    for i, utt in enumerate(utterances):
        # Window holds at most W utterances total (current + up to W-1
        # preceding) - see T26.1b/T26.3b: W=5 at index 9 -> indices 5-9.
        # W=0 degenerates to isolated embedding (T26.3): window is just `i`.
        start = i if W <= 0 else max(0, i - W + 1)
        window = utterances[start : i + 1]
        windows.append(
            WindowedUtterance(
                utterance_id=utt.id,
                seq=utt.seq,
                window_text=" ".join(u.text for u in window),
                window_size_actual=len(window),
                individual_text=utt.text,
            )
        )
    return windows

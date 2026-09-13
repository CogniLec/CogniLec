"""S26 — windowed embedding pipeline: build windows, embed, return per-utterance results."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from src.ml.embedding.client import EmbeddingClient
from src.ml.embedding.windowing import _HasSeqAndText, build_windows


@dataclass
class WindowedEmbeddingResult:
    utterance_id: uuid.UUID
    embedding: list[float]
    window_size_actual: int


async def embed_session_windowed(
    utterances: list[_HasSeqAndText],
    client: EmbeddingClient,
    W: int = 5,  # noqa: N803 - matches the spec's contract (S26 §5.3)
    task_mode: Literal["retrieval", "clustering"] = "clustering",
) -> list[WindowedEmbeddingResult]:
    """Embed all utterances in a session using context windows (S26 §5.2).

    Utterances must already be ordered by `seq`.
    """
    if not utterances:
        return []

    windows = build_windows(utterances, W=W)
    texts = [w.window_text for w in windows]
    vectors = await client.embed(texts, task_mode=task_mode)

    return [
        WindowedEmbeddingResult(
            utterance_id=w.utterance_id,
            embedding=vector,
            window_size_actual=w.window_size_actual,
        )
        for w, vector in zip(windows, vectors, strict=True)
    ]

"""Real pyannote.audio-backed DiarisationBackend (S20).

NOT installed in the shared project `.venv`: pyannote.audio 4.x pulls in
numpy>=2, which is ABI-incompatible with this repo's numpy 1.26.x pin and
breaks other packages (opencv, umap, hdbscan) built against numpy 1.x --
the same class of conflict documented for vLLM in docs/gaps.md gap #15.
This module is therefore only importable in an isolated environment that
has pyannote.audio installed (e.g. `uv venv` + `uv pip install pyannote.audio`
outside this repo's `.venv`), never in the shared one. The import is lazy
(inside __init__) so this file can still be imported and unit-tested for
its non-pyannote logic without pyannote.audio present.

NFR-S4: pyannote's `DiarizeOutput.speaker_embeddings` (a real per-speaker
voiceprint array) is deliberately never read or persisted anywhere -- only
`speaker_diarization`'s (start, end, local-speaker-label) turns are used,
matching the session-scoped, non-biometric SpeakerTag contract.

REFERENCE ONLY (gap #17/#18 follow-up): this direct-import class is kept
here as documentation of the shape pyannote's output takes and as a
standalone script/notebook entry point -- it is NOT the production wiring.
Production diarisation now goes through the isolated
`services/diarisation-service/` container (its `app.py` contains the same
pipeline logic, adapted into a FastAPI endpoint) via
`src/services/diarisation/http_backend.py`'s `HTTPDiarisationBackend`,
mirroring how S36 isolates vLLM as its own docker-compose service rather
than an in-process import. This file is left in place, unmodified in
behaviour, only as reference.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PyannoteSegment:
    start_ms: int
    end_ms: int
    speaker_index: int


class PyannoteBackend:
    """Wraps pyannote.audio's speaker-diarization-3.1 pipeline."""

    def __init__(self, hf_token: str, device: str = "cuda") -> None:
        import torch
        from pyannote.audio import Pipeline  # lazy: see module docstring

        self._pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=hf_token
        )
        if device == "cuda" and torch.cuda.is_available():
            self._pipeline.to(torch.device("cuda"))

    def diarise(self, audio_path: str, max_speakers: int) -> list[PyannoteSegment]:
        output = self._pipeline(audio_path, max_speakers=max_speakers)
        annotation = output.speaker_diarization

        label_to_index: dict[str, int] = {}
        segments: list[PyannoteSegment] = []
        for turn, _, label in annotation.itertracks(yield_label=True):
            if label not in label_to_index:
                label_to_index[label] = len(label_to_index)
            segments.append(
                PyannoteSegment(
                    start_ms=int(turn.start * 1000),
                    end_ms=int(turn.end * 1000),
                    speaker_index=label_to_index[label],
                )
            )
        return segments

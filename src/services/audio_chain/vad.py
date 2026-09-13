"""Silero VAD wrapper (S17)."""

from __future__ import annotations

import io
import logging
from functools import lru_cache

import numpy as np
import soundfile as sf
import torch
from src.services.audio_chain.models import VADRegion

logger = logging.getLogger(__name__)

SILERO_SAMPLE_RATE = 16000

FloatArray = np.ndarray[tuple[int, ...], np.dtype[np.float32]]


@lru_cache(maxsize=1)
def _load_model() -> object:
    from silero_vad import load_silero_vad

    return load_silero_vad()


class SileroVAD:
    """Speech-region detector backed by the Silero VAD ONNX/JIT model.

    Runs CPU-only in this environment (no GPU available); Silero VAD is a
    small model designed for CPU/edge use, so this is its normal mode, not a
    degraded fallback.
    """

    def __init__(self, threshold: float = 0.5, min_speech_ms: int = 250) -> None:
        self.threshold = threshold
        self.min_speech_ms = min_speech_ms

    def _model(self) -> object:
        return _load_model()

    def detect(self, audio: FloatArray, sample_rate: int) -> list[VADRegion]:
        """Detect speech regions in a float32 mono audio array."""
        try:
            from silero_vad import get_speech_timestamps

            tensor = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))
            timestamps = get_speech_timestamps(
                tensor,
                self._model(),
                threshold=self.threshold,
                sampling_rate=sample_rate,
                min_speech_duration_ms=self.min_speech_ms,
                return_seconds=False,
            )
            return [
                VADRegion(
                    start_ms=int(ts["start"] / sample_rate * 1000),
                    end_ms=int(ts["end"] / sample_rate * 1000),
                    confidence=float(ts.get("confidence", self.threshold)),
                )
                for ts in timestamps
            ]
        except Exception:
            # Fallback per spec section 8: assume all speech, emit whole chunk
            # as one region rather than silently dropping the chunk.
            logger.warning("Silero VAD failed; assuming full chunk is speech", exc_info=True)
            duration_ms = int(len(audio) / sample_rate * 1000)
            if duration_ms <= 0:
                return []
            return [VADRegion(start_ms=0, end_ms=duration_ms, confidence=0.5)]

    def has_speech(self, audio: FloatArray, sample_rate: int) -> bool:
        """Return True if any speech region is detected."""
        return len(self.detect(audio, sample_rate)) > 0


def read_wav_as_array(wav_bytes: bytes) -> tuple[FloatArray, int]:
    """Decode WAV bytes to a mono float32 numpy array + sample rate."""
    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1).astype(np.float32)
    return data, sr


def speech_ratio(regions: list[VADRegion], duration_ms: int) -> float:
    """Fraction of the chunk's duration covered by speech regions."""
    if duration_ms <= 0:
        return 0.0
    covered = sum(max(0, r.end_ms - r.start_ms) for r in regions)
    return min(1.0, covered / duration_ms)

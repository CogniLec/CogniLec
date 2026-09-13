"""Denoise stage: DeepFilterNet when available, ffmpeg `anlmdn` otherwise.

DeepFilterNet (`deepfilternet` / `df`) ships a Rust extension (`deepfilterlib`)
with no published wheel for this project's Python version (3.12) at the time
of writing, so it cannot be installed in this environment. The strategy
pattern here keeps the seam the spec calls for: if DeepFilterNet is
importable, use it; if the import fails, or the model OOMs at runtime, fall
back to the ffmpeg `anlmdn` filter (spec section 8 fallback instructions).
"""

from __future__ import annotations

import io
import logging
from typing import Any

import numpy as np
import soundfile as sf
from src.services.audio_chain.resample import denoise_anlmdn

logger = logging.getLogger(__name__)

try:
    from df.enhance import enhance, init_df, load_audio, save_audio

    _DEEPFILTERNET_AVAILABLE = True
except ImportError:
    _DEEPFILTERNET_AVAILABLE = False


class DeepFilterNetDenoiser:
    """Lazily-loaded DeepFilterNet model, forced onto CPU (no GPU in this env)."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._df_state: Any | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        self._model, self._df_state, _ = init_df()  # pragma: no cover - needs deepfilternet

    def denoise(self, wav_bytes: bytes) -> bytes:
        """Run DeepFilterNet enhancement on 16kHz mono WAV bytes."""
        self._ensure_loaded()
        assert self._df_state is not None
        buf_in = io.BytesIO(wav_bytes)
        audio, _ = load_audio(buf_in, sr=self._df_state.sr())
        enhanced = enhance(self._model, self._df_state, audio)
        buf_out = io.BytesIO()
        save_audio(buf_out, enhanced, self._df_state.sr())
        return buf_out.getvalue()


def denoise(wav_bytes: bytes, *, enabled: bool = True) -> tuple[bytes, bool]:
    """Denoise 16kHz mono WAV bytes. Returns (output_bytes, deepfilternet_applied).

    If `enabled` is False, or DeepFilterNet is unavailable, or it fails at
    runtime (e.g. OOM), falls back to the ffmpeg `anlmdn` filter and reports
    `deepfilternet_applied=False` so callers know which method actually ran.
    """
    if enabled and _DEEPFILTERNET_AVAILABLE:
        try:
            model = DeepFilterNetDenoiser()
            return model.denoise(wav_bytes), True
        except Exception:
            logger.warning("DeepFilterNet denoise failed; falling back to anlmdn", exc_info=True)

    return denoise_anlmdn(wav_bytes), False


def estimate_snr_db(wav_bytes: bytes) -> float:
    """Rough SNR estimate (dB) for test/diagnostic purposes.

    Splits the signal into fixed windows, treats the quietest 10% of window
    RMS values as the noise floor and the loudest 10% as signal peaks. This is
    a coarse heuristic suitable for comparing before/after denoise on
    synthetic fixtures, not a calibrated audio-engineering metric.
    """
    data, _sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if data.size == 0:
        return 0.0

    window = 400
    n_windows = max(1, data.size // window)
    rms = np.array(
        [
            float(np.sqrt(np.mean(np.square(data[i * window : (i + 1) * window])) + 1e-12))
            for i in range(n_windows)
        ]
    )
    rms_sorted = np.sort(rms)
    k = max(1, len(rms_sorted) // 10)
    noise_floor = float(np.mean(rms_sorted[:k]))
    signal_peak = float(np.mean(rms_sorted[-k:]))
    if noise_floor <= 1e-9:
        noise_floor = 1e-9
    return float(20.0 * np.log10(signal_peak / noise_floor))

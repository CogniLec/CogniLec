"""Chain orchestration: resample -> loudnorm -> denoise -> VAD (S17)."""

from __future__ import annotations

import logging
import time
from uuid import UUID

from src.services.audio_chain.denoise import denoise, estimate_snr_db
from src.services.audio_chain.models import PreprocessingResult, ProcessedChunk
from src.services.audio_chain.resample import (
    measure_lufs,
    probe_sample_rate,
    resample_and_normalize,
)
from src.services.audio_chain.vad import SileroVAD, read_wav_as_array, speech_ratio

logger = logging.getLogger(__name__)


class AudioPreprocessingChain:
    """Fixed pipeline: ffmpeg resample+loudnorm -> denoise -> Silero VAD."""

    def __init__(
        self,
        vad_threshold: float = 0.5,
        vad_min_speech_ms: int = 250,
        loudnorm_target_lufs: float = -23.0,
        loudnorm_tp: float = -2.0,
        chain_timeout_s: int = 3,
        deepfilter_enabled: bool = True,
    ) -> None:
        self.vad = SileroVAD(threshold=vad_threshold, min_speech_ms=vad_min_speech_ms)
        self.loudnorm_target_lufs = loudnorm_target_lufs
        self.loudnorm_tp = loudnorm_tp
        self.chain_timeout_s = chain_timeout_s
        self.deepfilter_enabled = deepfilter_enabled

    def process(
        self,
        input_bytes: bytes,
        session_id: UUID,
        sequence: int,
    ) -> PreprocessingResult:
        """Run one audio chunk through the full pre-processing chain."""
        start = time.monotonic()
        original_sample_rate = probe_sample_rate(input_bytes)

        resampled, lufs_before = resample_and_normalize(
            input_bytes,
            target_lufs=self.loudnorm_target_lufs,
            target_tp=self.loudnorm_tp,
        )

        snr_before = estimate_snr_db(resampled)
        denoised, denoise_applied = denoise(resampled, enabled=self.deepfilter_enabled)
        snr_after = estimate_snr_db(denoised)
        lufs_after = measure_lufs(denoised)

        audio_array, sample_rate = read_wav_as_array(denoised)
        duration_ms = int(len(audio_array) / sample_rate * 1000) if sample_rate else 0

        regions = self.vad.detect(audio_array, sample_rate)
        ratio = speech_ratio(regions, duration_ms)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        if elapsed_ms > self.chain_timeout_s * 1000:
            logger.warning(
                "preprocessing chain exceeded timeout",
                extra={
                    "session_id": str(session_id),
                    "sequence": sequence,
                    "elapsed_ms": elapsed_ms,
                },
            )

        chunk = ProcessedChunk(
            session_id=session_id,
            sequence=sequence,
            original_sample_rate=original_sample_rate,
            duration_ms=duration_ms,
            audio_data=denoised,
            vad_regions=regions,
            speech_ratio=ratio,
            has_speech=len(regions) > 0,
            processing_latency_ms=elapsed_ms,
        )
        return PreprocessingResult(
            chunk=chunk,
            lufs_before=lufs_before,
            lufs_after=lufs_after,
            snr_before=snr_before,
            snr_after=snr_after,
            denoise_applied=denoise_applied,
        )

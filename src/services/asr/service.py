"""faster-whisper transcription service producing word-timestamped Utterances.

CRITICAL TEST-ENVIRONMENT NOTE: the machine this was developed/verified on has
a broken NVIDIA driver (nvidia-smi fails with a driver/library version
mismatch), so there is no working GPU here. All functional verification in
tests/test_asr_worker.py runs this service with a small CPU model
(`tiny.en`, `compute_type="int8"`, `device="cpu"`) rather than the
production `large-v3`/`large-v3-turbo` model at production quantization.
This proves the transcription/persistence/state-machine mechanism works; it
does NOT verify production-model accuracy or GPU real-time-factor.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
from src.services.asr.align import align_words_wav2vec2
from src.services.asr.models import ASRResult, Utterance, WordTimestamp

log = logging.getLogger(__name__)


class FasterWhisperASRService:
    """Loads a faster-whisper model and transcribes audio into Utterances."""

    def __init__(
        self,
        model_name: str,
        compute_type: str,
        device: str,
        beam_size: int,
        language: str,
        embed_model_ver: str,
        word_timestamps: bool = True,
        alignment_model: str | None = None,
        alignment_enabled: bool = False,
        model: Any | None = None,
    ) -> None:
        self._model_name = model_name
        self._compute_type = compute_type
        self._device = device
        self._beam_size = beam_size
        self._language = language
        self._embed_model_ver = embed_model_ver
        self._word_timestamps = word_timestamps
        self._alignment_model = alignment_model
        self._alignment_enabled = alignment_enabled
        self._model = model or self._load_model()

    def _load_model(self) -> Any:
        from faster_whisper import WhisperModel

        start = time.monotonic()
        log.info(
            "loading faster-whisper model %s (compute_type=%s, device=%s)",
            self._model_name,
            self._compute_type,
            self._device,
        )
        model = WhisperModel(self._model_name, device=self._device, compute_type=self._compute_type)
        log.info("model load took %.2fs", time.monotonic() - start)
        return model

    def transcribe_chunk(
        self,
        audio: np.ndarray[Any, np.dtype[np.float32]],
        sample_rate: int,
        session_id: uuid.UUID,
        subject_id: uuid.UUID,
        sequence_start: int,
    ) -> ASRResult:
        """Transcribe one preprocessed audio chunk into utterances.

        `sequence_start` is the utterance sequence number for the first
        segment produced from this chunk; segments within a chunk are
        numbered sequence_start, sequence_start + 1, ...
        """
        total_duration_ms = int(len(audio) / sample_rate * 1000) if sample_rate else 0
        start = time.monotonic()

        segments, _info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=self._beam_size,
            word_timestamps=self._word_timestamps,
        )

        utterances: list[Utterance] = []
        seq = sequence_start
        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            seg_start_ms = int(segment.start * 1000)
            seg_end_ms = int(segment.end * 1000)

            words = self._words_for_segment(
                segment, text, audio, sample_rate, seg_start_ms, seg_end_ms
            )
            avg_confidence = self._segment_confidence(segment)

            utterances.append(
                Utterance(
                    session_id=session_id,
                    subject_id=subject_id,
                    sequence=seq,
                    text=text,
                    start_ms=seg_start_ms,
                    end_ms=max(seg_end_ms, seg_start_ms + 1),
                    confidence=avg_confidence,
                    words=words,
                    embed_model_ver=self._embed_model_ver,
                    speaker_tag=None,
                    created_at=datetime.now(UTC),
                )
            )
            seq += 1

        processing_time_ms = int((time.monotonic() - start) * 1000)
        rtf = (processing_time_ms / total_duration_ms) if total_duration_ms > 0 else 0.0

        return ASRResult(
            session_id=session_id,
            utterances=utterances,
            total_duration_ms=total_duration_ms,
            processing_time_ms=processing_time_ms,
            real_time_factor=rtf,
            model_name=self._model_name,
            model_quantization=self._compute_type,
        )

    def _words_for_segment(
        self,
        segment: Any,
        text: str,
        audio: np.ndarray[Any, np.dtype[np.float32]],
        sample_rate: int,
        seg_start_ms: int,
        seg_end_ms: int,
    ) -> list[WordTimestamp]:
        """Word-level timestamps: wav2vec2 alignment if enabled, else native."""
        if self._alignment_enabled and self._alignment_model:
            start_sample = int(seg_start_ms / 1000 * sample_rate)
            end_sample = int(seg_end_ms / 1000 * sample_rate)
            aligned = align_words_wav2vec2(
                audio[start_sample:end_sample],
                sample_rate,
                text,
                seg_start_ms,
                seg_end_ms,
                self._alignment_model,
                device="cpu",
            )
            if aligned is not None:
                return aligned
            log.warning("alignment fallback to faster-whisper native word timestamps")

        return self._native_words(segment, text, seg_start_ms, seg_end_ms)

    @staticmethod
    def _native_words(
        segment: Any, text: str, seg_start_ms: int, seg_end_ms: int
    ) -> list[WordTimestamp]:
        """faster-whisper's own word-level timestamps, or a segment-level fallback."""
        raw_words = getattr(segment, "words", None)
        if raw_words:
            result: list[WordTimestamp] = []
            prev_end = seg_start_ms
            for w in raw_words:
                start_ms = max(int(w.start * 1000), prev_end)
                end_ms = max(int(w.end * 1000), start_ms + 1)
                result.append(
                    WordTimestamp(
                        word=w.word.strip(),
                        start_ms=start_ms,
                        end_ms=end_ms,
                        confidence=min(max(float(getattr(w, "probability", 0.5)), 0.0), 1.0),
                    )
                )
                prev_end = end_ms
            if result:
                return result

        # Fall back to a single segment-level "word" spanning the whole segment.
        return [
            WordTimestamp(
                word=text,
                start_ms=seg_start_ms,
                end_ms=max(seg_end_ms, seg_start_ms + 1),
                confidence=0.5,
            )
        ]

    @staticmethod
    def _segment_confidence(segment: Any) -> float:
        avg_logprob = getattr(segment, "avg_logprob", None)
        if avg_logprob is None:
            return 0.5
        # avg_logprob is a log-probability, typically in [-1, 0] for reasonable
        # transcriptions; map to [0, 1] and clamp.
        confidence = float(np.exp(avg_logprob))
        return min(max(confidence, 0.0), 1.0)

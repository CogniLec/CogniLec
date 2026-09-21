"""External (hosted) ASR backend -- drop-in alternative to FasterWhisperASRService.

Speaks the OpenAI-compatible `POST {base_url}/audio/transcriptions` API, which
Groq, OpenAI, Together, and self-hosted faster-whisper-server all expose, so
one client covers any of them by changing config only.

Why this is safe to swap in: everything downstream of ASR (T1-T7) consumes
only utterance `seq` (ordinal position) and text -- confirmed by reading
segmentation.py / relevance_filter.py / note_synthesis.py, none of which read
word- or utterance-level timestamps. So a provider that returns only ordered
text (or coarse segment timings) is sufficient. When the provider returns
`verbose_json` segments we use them (one Utterance per segment, as the local
backend does); otherwise the whole chunk becomes a single utterance.

Motivation (docs/audit/pipeline-overhaul.md, docs/about.md): the shared 4GB
GPU on the ASR host is already claimed by vLLM, so local GPU ASR OOMs and CPU
ASR cannot keep real-time pace on a 60+ minute live recording.
"""

from __future__ import annotations

import io
import logging
import time
import uuid
import wave
from datetime import UTC, datetime
from typing import Any

import httpx
import numpy as np
from src.services.asr.models import ASRResult, Utterance, WordTimestamp

log = logging.getLogger(__name__)


class ExternalASRError(RuntimeError):
    """Raised when the hosted transcription call fails."""


def _to_wav_bytes(audio: np.ndarray[Any, np.dtype[np.float32]], sample_rate: int) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


class ExternalASRService:
    """Same `transcribe_chunk` contract as FasterWhisperASRService."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        language: str,
        embed_model_ver: str,
        timeout_s: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/audio/transcriptions"
        self._api_key = api_key
        self._model = model
        self._language = language
        self._embed_model_ver = embed_model_ver
        self._client = client or httpx.Client(timeout=timeout_s)

    def transcribe_chunk(
        self,
        audio: np.ndarray[Any, np.dtype[np.float32]],
        sample_rate: int,
        session_id: uuid.UUID,
        subject_id: uuid.UUID,
        sequence_start: int,
    ) -> ASRResult:
        total_duration_ms = int(len(audio) / sample_rate * 1000) if sample_rate else 0
        start = time.monotonic()

        try:
            resp = self._client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                files={"file": ("chunk.wav", _to_wav_bytes(audio, sample_rate), "audio/wav")},
                data={
                    "model": self._model,
                    "language": self._language,
                    "response_format": "verbose_json",
                },
            )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            msg = f"external ASR request failed: {exc}"
            raise ExternalASRError(msg) from exc

        segments = body.get("segments") or []
        pieces: list[tuple[str, int, int]] = []
        for seg in segments:
            text = str(seg.get("text", "")).strip()
            if text:
                pieces.append(
                    (
                        text,
                        int(float(seg.get("start", 0)) * 1000),
                        int(float(seg.get("end", 0)) * 1000),
                    )
                )
        if not pieces:
            text = str(body.get("text", "")).strip()
            if text:
                pieces.append((text, 0, total_duration_ms))

        utterances: list[Utterance] = []
        for offset, (text, s_ms, e_ms) in enumerate(pieces):
            e_ms = max(e_ms, s_ms + 1)
            utterances.append(
                Utterance(
                    session_id=session_id,
                    subject_id=subject_id,
                    sequence=sequence_start + offset,
                    text=text,
                    start_ms=s_ms,
                    end_ms=e_ms,
                    confidence=0.5,
                    words=[WordTimestamp(word=text, start_ms=s_ms, end_ms=e_ms, confidence=0.5)],
                    embed_model_ver=self._embed_model_ver,
                    speaker_tag=None,
                    created_at=datetime.now(UTC),
                )
            )

        processing_time_ms = int((time.monotonic() - start) * 1000)
        return ASRResult(
            session_id=session_id,
            utterances=utterances,
            total_duration_ms=total_duration_ms,
            processing_time_ms=processing_time_ms,
            real_time_factor=(processing_time_ms / total_duration_ms) if total_duration_ms else 0.0,
            model_name=self._model,
            model_quantization="hosted",
        )

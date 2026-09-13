"""Optional wav2vec2 forced-alignment pass for word-level timestamps.

faster-whisper already produces word-level timestamps natively (via its
internal cross-attention alignment) when `word_timestamps=True`, which is
sufficient to satisfy T19.2 (monotonic word timestamps). This module adds
the spec's wav2vec2 forced-alignment pass as an optional refinement on top
of that: when enabled and successful it can produce tighter alignment, but
on any failure (model unavailable, alignment collapse on a short utterance,
etc.) the caller falls back to faster-whisper's native word timestamps per
the S19 edge-case table ("Alignment fails on word -> fall back to
segment-level timestamps").
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from src.services.asr.models import WordTimestamp

log = logging.getLogger(__name__)

_ALIGNER_CACHE: dict[str, tuple[Any, Any]] = {}


def _load_aligner(model_id: str, device: str) -> tuple[Any, Any]:
    """Lazily load and cache a wav2vec2 CTC model + processor."""
    key = f"{model_id}:{device}"
    if key not in _ALIGNER_CACHE:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        processor = Wav2Vec2Processor.from_pretrained(model_id)
        model = Wav2Vec2ForCTC.from_pretrained(model_id).to(device).eval()
        _ALIGNER_CACHE[key] = (model, processor)
    return _ALIGNER_CACHE[key]


def align_words_wav2vec2(
    audio: np.ndarray[Any, np.dtype[np.float32]],
    sample_rate: int,
    text: str,
    segment_start_ms: int,
    segment_end_ms: int,
    model_id: str,
    device: str = "cpu",
) -> list[WordTimestamp] | None:
    """Attempt wav2vec2 forced alignment of `text` against `audio`.

    Returns None (never raises) if alignment cannot be produced, so the
    caller can fall back to faster-whisper's native word timestamps.
    """
    words = text.split()
    if not words:
        return None
    try:
        import torch

        model, processor = _load_aligner(model_id, device)

        inputs = processor(audio, sampling_rate=sample_rate, return_tensors="pt")
        with torch.no_grad():
            logits = model(inputs.input_values.to(device)).logits[0]
        emissions = torch.log_softmax(logits, dim=-1).cpu()

        tokenizer = processor.tokenizer
        transcript = "|".join(words).upper()
        token_ids = [tokenizer.convert_tokens_to_ids(c) for c in transcript]
        if any(t is None or t < 0 for t in token_ids):
            return None
        targets = torch.tensor([token_ids], dtype=torch.int32)
        input_lengths = torch.tensor([emissions.shape[0]], dtype=torch.int32)
        target_lengths = torch.tensor([len(token_ids)], dtype=torch.int32)

        import torchaudio

        alignments, align_scores = torchaudio.functional.forced_align(
            emissions.unsqueeze(0),
            targets,
            input_lengths,
            target_lengths,
            blank=tokenizer.pad_token_id,
        )
        token_spans = torchaudio.functional.merge_tokens(alignments[0], align_scores[0])

        duration_ms = segment_end_ms - segment_start_ms
        num_frames = emissions.shape[0]
        ms_per_frame = duration_ms / num_frames if num_frames else 0.0

        word_spans: list[WordTimestamp] = []
        current_word: list[Any] = []
        word_idx = 0
        for span in token_spans:
            char = transcript[span.token] if span.token < len(transcript) else "|"
            if char == "|":
                if current_word and word_idx < len(words):
                    start_ms = segment_start_ms + int(current_word[0].start * ms_per_frame)
                    end_ms = segment_start_ms + int(current_word[-1].end * ms_per_frame)
                    conf = float(np.mean([s.score for s in current_word]))
                    word_spans.append(
                        WordTimestamp(
                            word=words[word_idx],
                            start_ms=start_ms,
                            end_ms=max(end_ms, start_ms + 1),
                            confidence=min(max(conf, 0.0), 1.0),
                        )
                    )
                    word_idx += 1
                current_word = []
            else:
                current_word.append(span)
        if current_word and word_idx < len(words):
            start_ms = segment_start_ms + int(current_word[0].start * ms_per_frame)
            end_ms = segment_start_ms + int(current_word[-1].end * ms_per_frame)
            conf = float(np.mean([s.score for s in current_word]))
            word_spans.append(
                WordTimestamp(
                    word=words[word_idx],
                    start_ms=start_ms,
                    end_ms=max(end_ms, start_ms + 1),
                    confidence=min(max(conf, 0.0), 1.0),
                )
            )

        if len(word_spans) != len(words):
            return None
        else:
            return word_spans
    except Exception as exc:
        log.warning("wav2vec2 forced alignment failed, falling back: %s", exc)
        return None

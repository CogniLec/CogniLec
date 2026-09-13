"""ASR model loading and transcription — supports faster-whisper and NeMo."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def load_faster_whisper(model_id: str, compute_type: str, device: str = "cuda") -> Any:
    """Load a Whisper model via faster-whisper (CTranslate2).

    Args:
        model_id: HuggingFace model ID or local path
        compute_type: quantization mode (fp16, int8_float16, int8)
        device: cuda or cpu

    Returns:
        faster_whisper.WhisperModel instance
    """
    from faster_whisper import WhisperModel

    log.info(
        "Loading faster-whisper model %s (compute_type=%s, device=%s)",
        model_id,
        compute_type,
        device,
    )
    return WhisperModel(model_id, device=device, compute_type=compute_type)


def load_nemo_parakeet(model_id: str, device: str = "cuda") -> Any:
    """Load Parakeet TDT via NeMo toolkit.

    Args:
        model_id: HuggingFace model ID
        device: cuda or cpu

    Returns:
        NeMo EncDecRNNTBPEModel on device in eval mode
    """
    from nemo.collections.asr.models import EncDecRNNTBPEModel

    log.info("Loading NeMo Parakeet model %s", model_id)
    model = EncDecRNNTBPEModel.from_pretrained(model_id)
    model = getattr(model, device)().eval()  # model.cuda() or model.cpu()
    return model


def load_canary(model_id: str, compute_type: str = "int8_float16", device: str = "cuda") -> Any:
    """Load NVIDIA Canary via faster-whisper.

    Canary uses the Whisper-compatible CT2 format.
    """
    return load_faster_whisper(model_id, compute_type, device)


def load_model(
    name: str, model_id: str, compute_type: str, engine: str, device: str = "cuda"
) -> Any:
    """Dispatch model loading by engine type.

    Args:
        name: human-readable model name (e.g. "whisper-large-v3")
        model_id: model path or HuggingFace ID
        compute_type: quantization mode
        engine: "faster_whisper" | "nemo"
        device: cuda or cpu

    Returns:
        Loaded model object
    """
    if engine == "faster_whisper":
        return load_faster_whisper(model_id, compute_type, device)
    elif engine == "nemo":
        return load_nemo_parakeet(model_id, device)
    else:
        msg = f"Unknown engine: {engine} for model {name}"
        raise ValueError(msg)


def transcribe(model: Any, audio_path: Path, engine: str, beam_size: int = 5) -> str:
    """Transcribe an audio file with the given model.

    Args:
        model: loaded model object
        audio_path: path to audio file
        engine: "faster_whisper" | "nemo"
        beam_size: beam size for faster-whisper

    Returns:
        Transcribed text
    """
    if engine == "faster_whisper":
        segments, _ = model.transcribe(str(audio_path), beam_size=beam_size)
        return " ".join(seg.text for seg in segments)
    elif engine == "nemo":
        return _transcribe_nemo(model, audio_path)
    else:
        msg = f"Unknown engine: {engine}"
        raise ValueError(msg)


def _transcribe_nemo(model: Any, audio_path: Path) -> str:
    """Transcribe with NeMo model (with fallback for older versions)."""
    try:
        import torchaudio

        waveform, sr = torchaudio.load(str(audio_path))
        target_sr = getattr(model.preprocessor, "_sample_rate", 16000)
        if sr != target_sr:
            waveform = torchaudio.functional.resample(waveform, sr, target_sr)
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        import torch

        with torch.no_grad():
            hyp = model.transcribe([waveform.cuda()])[0]
        if hasattr(hyp, "text"):
            return str(hyp.text)
        return str(hyp)
    except Exception:
        log.exception("NeMo transcription failed")
        raise

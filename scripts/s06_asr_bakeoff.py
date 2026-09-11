#!/usr/bin/env python3
"""S06 ASR Bake-Off — Evaluate 4 ASR models across acoustic conditions.

Constraints:
  - 4GB VRAM: only one model loaded at a time, sequential evaluation
  - 8-bit quantization for models >2.5GB FP16
  - MLflow tracking at http://mlflow:5000
  - Whisper normalizer applied to reference and hypothesis
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import jiwer
import mlflow
import pandas as pd
import torch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
EXPERIMENT_NAME = "S06_ASR_Bakeoff"


# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------
@dataclass
class ASRModelSpec:
    name: str
    model_id: str
    compute_type: str
    engine: str  # "faster_whisper" | "nemo"


ASR_MODELS = [
    ASRModelSpec("whisper-large-v3", "large-v3", "int8_float16", "faster_whisper"),
    ASRModelSpec("whisper-large-v3-turbo", "large-v3-turbo", "fp16", "faster_whisper"),
    ASRModelSpec("canary-qwen-2.5b", "nvidia/canary-25b-12b-pt", "int8_float16", "faster_whisper"),
    ASRModelSpec("parakeet-tdt-1.1b", "nvidia/parakeet-tdt-1.1b", "fp16", "nemo"),
]

# ---------------------------------------------------------------------------
# Audio conditions — resolved from S04 manifest at runtime
# ---------------------------------------------------------------------------
CONDITIONS = [
    "front_quiet",
    "back_quiet",
    "front_busy",
    "back_busy",
    "lecturer_moving",
    "heavy_discussion",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def discover_audio(condition: str) -> list[Path]:
    """Discover audio files for a given condition from the S04 corpus."""
    corpus = Path("data/corpus")
    manifest = corpus / "manifest.jsonl"
    if manifest.exists():
        files: list[Path] = []
        with open(manifest) as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("condition") == condition:
                    p = corpus / rec["audio_path"]
                    if p.exists():
                        files.append(p)
        return files

    # Fallback: glob by condition prefix
    patterns = [f"**/{condition}*.wav", f"**/{condition}*.mp3", f"**/{condition}*.flac"]
    found: list[Path] = []
    for pat in patterns:
        found.extend(corpus.glob(pat))
    return sorted(set(found))


def discover_references(audio_path: Path) -> str | None:
    """Load ground-truth transcript for an audio file from S05."""
    gt_dir = Path("data/ground_truth")
    stem = audio_path.stem
    for ext in [".txt", ".json"]:
        ref = gt_dir / f"{stem}{ext}"
        if ref.exists():
            if ext == ".json":
                with open(ref) as f:
                    data = json.load(f)
                return data.get("transcript", data.get("text", ""))
            return ref.read_text().strip()
    return None


def whisper_normalizer(text: str) -> str:
    """Normalize text using jiwer's Whisper-compatible normalizer."""
    return jiwer.ToLowerCase()(
        jiwer.RemovePunctuation()(jiwer.RemoveMultipleSpaces()(text.strip()))
    )


def load_faster_whisper(model_id: str, compute_type: str):
    """Load a Whisper model via faster-whisper."""
    from faster_whisper import WhisperModel

    log.info("Loading faster-whisper model %s (compute_type=%s)", model_id, compute_type)
    return WhisperModel(model_id, device="cuda", compute_type=compute_type)


def load_nemo_parakeet(model_id: str):
    """Load Parakeet via NeMo."""
    try:
        from nemo.collections.asr.models import EncDecRNNTBPEModel

        log.info("Loading NeMo model %s", model_id)
        model = EncDecRNNTBPEModel.from_pretrained(model_id)
        model = model.cuda().eval()
        return model
    except Exception as e:
        log.error("Failed to load NeMo model %s: %s", model_id, e)
        raise


def transcribe_faster_whisper(model, audio_path: Path, beam_size: int = 5) -> str:
    """Transcribe with faster-whisper."""
    segments, _ = model.transcribe(str(audio_path), beam_size=beam_size)
    return " ".join(seg.text for seg in segments)


def transcribe_nemo(model, audio_path: Path) -> str:
    """Transcribe with NeMo Parakeet."""
    try:
        from nemo.collections.asr.parts.utils.transcribe_utils import (
            TranscriptionConfig,
            transcribe_audio,
        )

        cfg = TranscriptionConfig()
        result = transcribe_audio(model, str(audio_path), cfg)
        if isinstance(result, tuple):
            return result[0] if result[0] else ""
        return str(result)
    except ImportError:
        # Manual fallback for older NeMo
        import torchaudio

        waveform, sr = torchaudio.load(str(audio_path))
        if sr != model.preprocessor._sample_rate:
            waveform = torchaudio.functional.resample(waveform, sr, model.preprocessor._sample_rate)
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        with torch.no_grad():
            hyp = model.transcribe([waveform.cuda()])[0]
        if hasattr(hyp, "text"):
            return hyp.text
        return str(hyp)


def compute_vram_peak_mb() -> float:
    """Return current CUDA VRAM peak in MB."""
    if torch.cuda.is_available():
        return torch.cuda.max_memory_allocated() / (1024 * 1024)
    return 0.0


def get_audio_duration_sec(audio_path: Path) -> float:
    """Get audio duration in seconds."""
    try:
        import soundfile as sf

        info = sf.info(str(audio_path))
        return info.duration
    except Exception:
        return 1.0  # fallback


# ---------------------------------------------------------------------------
# Main bake-off
# ---------------------------------------------------------------------------
def run_bakeoff():
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    results: list[dict] = []

    for spec in ASR_MODELS:
        log.info("===== Evaluating %s =====", spec.name)
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

        # Load model
        try:
            if spec.engine == "faster_whisper":
                model = load_faster_whisper(spec.model_id, spec.compute_type)
            elif spec.engine == "nemo":
                model = load_nemo_parakeet(spec.model_id)
            else:
                log.error("Unknown engine %s for %s", spec.engine, spec.name)
                continue
        except Exception as e:
            log.error("Failed to load %s: %s", spec.name, e)
            continue

        for condition in CONDITIONS:
            audio_files = discover_audio(condition)
            if not audio_files:
                log.warning("No audio files for condition=%s, skipping", condition)
                continue

            log.info("Condition=%s: %d files", condition, len(audio_files))

            for audio_path in audio_files:
                reference = discover_references(audio_path)
                if reference is None:
                    log.warning("No reference for %s, skipping", audio_path.name)
                    continue

                run_name = f"{spec.name}_{condition}_{audio_path.stem}"

                with mlflow.start_run(run_name=run_name):
                    # Log params
                    mlflow.log_params(
                        {
                            "model": spec.name,
                            "condition": condition,
                            "quantization": spec.compute_type,
                            "compute_type": spec.compute_type,
                            "engine": spec.engine,
                            "audio_file": audio_path.name,
                        }
                    )

                    # Transcribe
                    t0 = time.time()
                    if spec.engine == "faster_whisper":
                        hypothesis = transcribe_faster_whisper(model, audio_path)
                    else:
                        hypothesis = transcribe_nemo(model, audio_path)
                    elapsed = time.time() - t0

                    # Normalize
                    hyp_norm = whisper_normalizer(hypothesis)
                    ref_norm = whisper_normalizer(reference)

                    # Compute metrics
                    wer = jiwer.wer(ref_norm, hyp_norm)
                    cer = jiwer.cer(ref_norm, hyp_norm)
                    duration = get_audio_duration_sec(audio_path)
                    rtf = elapsed / duration if duration > 0 else 0.0
                    vram_peak = compute_vram_peak_mb()

                    mlflow.log_metrics(
                        {
                            "wer": wer,
                            "cer": cer,
                            "rtf": rtf,
                            "vram_peak_mb": vram_peak,
                            "audio_duration_sec": duration,
                            "inference_time_sec": elapsed,
                        }
                    )

                    # Log artifacts
                    hyp_path = Path("tmp_hypothesis.txt")
                    hyp_path.write_text(hypothesis)
                    mlflow.log_artifact(str(hyp_path), "hypothesis")
                    hyp_path.unlink(missing_ok=True)

                    ref_path = Path("tmp_reference.txt")
                    ref_path.write_text(reference)
                    mlflow.log_artifact(str(ref_path), "reference")
                    ref_path.unlink(missing_ok=True)

                    mlflow.set_tag("mlflow.runName", run_name)

                    log.info(
                        "  %s | WER=%.3f CER=%.3f RTF=%.3f VRAM=%.0fMB",
                        audio_path.name,
                        wer,
                        cer,
                        rtf,
                        vram_peak,
                    )

                    results.append(
                        {
                            "model": spec.name,
                            "condition": condition,
                            "wer": wer,
                            "cer": cer,
                            "rtf": rtf,
                            "vram_peak_mb": vram_peak,
                            "quantization": spec.compute_type,
                            "compute_type": spec.compute_type,
                        }
                    )

        # Unload model
        del model
        torch.cuda.empty_cache()
        log.info("Unloaded %s — VRAM freed", spec.name)

    # Save aggregated CSV
    if results:
        df = pd.DataFrame(results)
        csv_path = Path("docs/bakeoff-asr-results.csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(csv_path, index=False)
        log.info("ASR results saved to %s", csv_path)

    return results


if __name__ == "__main__":
    try:
        run_bakeoff()
        log.info("ASR bake-off complete")
    except Exception as e:
        log.error("ASR bake-off failed: %s", e, exc_info=True)
        sys.exit(1)

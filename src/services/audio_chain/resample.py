"""ffmpeg-backed resampling and EBU R128 loudness normalization (S17)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import lru_cache

import imageio_ffmpeg

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1


class FfmpegNotAvailableError(RuntimeError):
    """Raised when no ffmpeg binary can be located (hard dependency)."""


@lru_cache(maxsize=1)
def resolve_ffmpeg_binary() -> str:
    """Locate an ffmpeg executable: system PATH first, else the bundled static binary.

    ffmpeg is a hard dependency (spec section 8) — fail fast with a clear error
    if neither a system binary nor the bundled fallback is available.
    """
    system_binary = shutil.which("ffmpeg")
    if system_binary:
        return system_binary
    try:
        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception as exc:  # pragma: no cover - only hit with no ffmpeg at all
        msg = "ffmpeg is not available on this system (no system binary, no bundled fallback)"
        raise FfmpegNotAvailableError(msg) from exc


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    binary = resolve_ffmpeg_binary()
    result = subprocess.run(
        [binary, *args],
        capture_output=True,
        check=False,
    )
    return result


def probe_sample_rate(input_bytes: bytes, default_sample_rate: int = 48000) -> int:
    """Best-effort probe of the input's sample rate via ffmpeg stderr banner.

    Falls back to `default_sample_rate` (48kHz, the Opus standard per the edge
    case matrix) when the rate cannot be determined.
    """
    binary = resolve_ffmpeg_binary()
    proc = subprocess.run(
        [binary, "-i", "pipe:0", "-f", "null", "-"],
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    match = re.search(rb"(\d+) Hz", proc.stderr)
    if match:
        return int(match.group(1))
    return default_sample_rate


def resample_and_normalize(
    input_bytes: bytes,
    target_lufs: float = -23.0,
    target_tp: float = -2.0,
    target_lra: float = 11.0,
) -> tuple[bytes, float | None]:
    """Resample to 16kHz mono WAV and apply single-pass EBU R128 loudnorm.

    Returns (wav_bytes, measured_input_lufs_or_none). The measured input LUFS
    comes from ffmpeg's loudnorm `print_format=json` stats (single-pass, per
    spec section 8: "single-pass acceptable for real-time").
    """
    if not input_bytes:
        msg = "input audio is empty"
        raise ValueError(msg)

    loudnorm_filter = f"loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}:print_format=json"
    args = [
        "-i",
        "pipe:0",
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-ac",
        str(TARGET_CHANNELS),
        "-af",
        loudnorm_filter,
        "-f",
        "wav",
        "pipe:1",
    ]
    binary = resolve_ffmpeg_binary()
    proc = subprocess.run(
        [binary, *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        stderr_text = proc.stderr.decode(errors="replace")[:2000]
        msg = f"ffmpeg resample/loudnorm failed (rc={proc.returncode}): {stderr_text}"
        raise RuntimeError(msg)

    lufs_before = _extract_loudnorm_input_i(proc.stderr)
    return proc.stdout, lufs_before


def _extract_loudnorm_input_i(stderr: bytes) -> float | None:
    """Pull `input_i` (measured input LUFS) out of loudnorm's JSON stats block."""
    text = stderr.decode(errors="replace")
    brace_start = text.rfind("{")
    if brace_start == -1:
        return None
    brace_end = text.find("}", brace_start)
    if brace_end == -1:
        return None
    try:
        stats = json.loads(text[brace_start : brace_end + 1])
        return float(stats["input_i"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def measure_lufs(wav_bytes: bytes) -> float | None:
    """Measure integrated LUFS of WAV bytes without modifying the audio."""
    binary = resolve_ffmpeg_binary()
    proc = subprocess.run(
        [binary, "-i", "pipe:0", "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        input=wav_bytes,
        capture_output=True,
        check=False,
    )
    return _extract_loudnorm_input_i(proc.stderr)


def denoise_anlmdn(wav_bytes: bytes) -> bytes:
    """Fallback denoise via ffmpeg's `anlmdn` filter (non-local means denoiser).

    Used when DeepFilterNet is unavailable or OOMs (spec edge case matrix).
    """
    binary = resolve_ffmpeg_binary()
    proc = subprocess.run(
        [binary, "-i", "pipe:0", "-af", "anlmdn", "-f", "wav", "pipe:1"],
        input=wav_bytes,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        stderr_text = proc.stderr.decode(errors="replace")[:2000]
        msg = f"ffmpeg anlmdn denoise failed (rc={proc.returncode}): {stderr_text}"
        raise RuntimeError(msg)
    return proc.stdout

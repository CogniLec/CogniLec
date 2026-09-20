"""Regression test for docs/gaps.md #33i: MP4 uploads previously had no
allowlist entry, and even with one added, ffmpeg piped input via stdin
(`-i pipe:0`) cannot decode an MP4 whose `moov` atom sits at the end of
the file (the common layout for phone/screen recordings that were never
"fast-started"). This generates a REAL such file with ffmpeg (no
`-movflags faststart`, `moov` written after `mdat`) and proves the fixed
temp-file-based ingestion path can actually probe and chunk it, not just
that the extension is now in an allowlist.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from src.services.audio_file_ingestion import (
    ALLOWED_AUDIO_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    _probe_duration_ms,
    _split_audio_chunk,
)

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _make_moov_at_end_mp4(path: str, duration_s: float = 2.0) -> None:
    """Generate a real MP4 with an audio tone, moov atom deliberately at
    the end (no faststart) -- the exact layout that broke stdin piping."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration_s}",
            "-c:a",
            "aac",
            path,
        ],
        capture_output=True,
        check=True,
    )


def test_mp4_and_video_mime_types_are_allowed() -> None:
    assert ".mp4" in ALLOWED_AUDIO_EXTENSIONS
    assert "video/mp4" in ALLOWED_MIME_TYPES


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe not available in this environment")
def test_real_mp4_with_moov_at_end_is_probed_and_chunked() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        mp4_path = str(Path(tmp_dir) / "lecture.mp4")
        _make_moov_at_end_mp4(mp4_path, duration_s=2.0)

        duration_ms = _probe_duration_ms(mp4_path)
        assert duration_ms > 1500  # ~2000ms, allow encoder rounding

        chunk_bytes = _split_audio_chunk(mp4_path, start_ms=0, duration_ms=duration_ms)
        assert len(chunk_bytes) > 0

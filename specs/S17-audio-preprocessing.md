# S17 — Audio Pre-Processing Chain
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Process audio chunks through a fixed chain (ffmpeg resampling → DeepFilterNet denoise → Silero VAD) to remove silence and steady noise before ASR, preventing Whisper hallucination.

**Component Boundaries:**
- **Allowed:** `src/workers/preprocessing_worker.py`, `src/services/audio_chain/`, `tests/test_preprocessing.py`, `tests/fixtures/audio/`
- **Off-limits:** ASR worker (S19), chunk upload (S16), quality metrics (S18)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| ffmpeg | 6.x | Resampling, loudness normalization |
| DeepFilterNet | 3.x | Noise reduction |
| Silero VAD | 5.x | Voice activity detection |
| numpy | 1.26.x | Audio array manipulation |
| soundfile | 0.12.x | Audio I/O |

---

### 2. State Machine & Domain Schemas

**Processing Chain State:**
```
RECEIVED → RESAMPLED → DENOISED → VAD_PROCESSED → EMITTED
    ↓          ↓           ↓            ↓
  FAILED     FAILED      FAILED       FAILED
```

**Processed Chunk Schema:**
```python
# src/services/audio_chain/models.py
from pydantic import BaseModel, Field
from uuid import UUID


class VADRegion(BaseModel):
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)


class ProcessedChunk(BaseModel):
    session_id: UUID
    sequence: int
    original_sample_rate: int
    output_sample_rate: int = 16000
    output_channels: int = 1
    duration_ms: int
    audio_data: bytes  # 16kHz mono float32 PCM
    vad_regions: list[VADRegion]
    speech_ratio: float = Field(..., ge=0.0, le=1.0)
    has_speech: bool
    processing_latency_ms: int


class PreprocessingResult(BaseModel):
    chunk: ProcessedChunk
    lufs_before: float | None = None
    lufs_after: float | None = None
    snr_before: float | None = None
    snr_after: float | None = None
    denoise_applied: bool
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Implement ffmpeg resampling to 16kHz mono | Output is 16kHz mono regardless of input |
| 2 | Implement EBU R128 loudness normalization | LUFS within target range |
| 3 | Implement DeepFilterNet denoise | SNR improved on noisy sample |
| 4 | Implement Silero VAD | Pure silence produces zero speech regions |
| 5 | Implement chain orchestration | Chain processes 30s chunk in < 3s |
| 6 | Implement Valkey Stream consumer | Worker consumes `audio.chunk` stream |
| 7 | Implement processed chunk output | VAD map emitted with processed audio |
| 8 | Run evaluation tests | All T17.x tests pass |

**Atomic Sub-tasks:**
1. ffmpeg resampling and loudnorm
2. DeepFilterNet denoise integration
3. Silero VAD integration
4. Chain orchestration
5. Stream consumer
6. Processed chunk output

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Input sample rate unknown | Default to 48kHz (Opus standard) |
| Input is not audio | Reject with error, do not process |
| DeepFilterNet OOM | Fall back to ffmpeg-only denoise |
| VAD produces no regions | Mark `has_speech=false`; still emit chunk |
| Chain exceeds 3s timeout | Log warning; still process (best effort) |
| Chunk is pure silence | VAD returns empty regions; `speech_ratio=0` |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Pipeline pattern: fixed chain of transforms
- Worker pattern: Valkey Stream consumer
- Strategy pattern: denoise method configurable (DeepFilterNet vs fallback)
- Observer pattern: processing metrics emitted at each stage

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`preprocessing_worker.py`, `audio_chain.py`)
- Functions: snake_case
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Valkey Stream Consumer:**
```python
# Stream: audio.chunk
# Consumer Group: preprocessing
# Consumer: preprocessing-worker-1

XREADGROUP GROUP preprocessing preprocessing-worker-1 COUNT 10 BLOCK 5000 STREAMS audio.chunk >

# Message fields:
{
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "subject_id": "660e8400-e29b-41d4-a716-446655440000",
    "sequence": "0",
    "timestamp_ms": "0",
    "duration_ms": "30000",
    "object_key": "550e8400.../chunks/00000.opus"
}
```

**Processed Chunk Output Stream:**
```yaml
Stream: audio.processed
Fields:
  session_id: "550e8400-e29b-41d4-a716-446655440000"
  sequence: "0"
  object_key: "550e8400.../processed/00000.wav"
  has_speech: "true"
  speech_ratio: "0.72"
  vad_regions: "[{\"start_ms\":0,\"end_ms\":5000,\"confidence\":0.95},{\"start_ms\":6000,\"end_ms\":15000,\"confidence\":0.88}]"
  processing_latency_ms: "2100"
```

**ffmpeg Command Template:**
```bash
ffmpeg -i {input} \
  -ar 16000 \
  -ac 1 \
  -af "loudnorm=I=-23:TP=-2:LRA=11:print_format=json" \
  -f wav \
  pipe:1
```

**Silero VAD Interface:**
```python
# src/services/audio_chain/vad.py
class SileroVAD:
    def __init__(self, threshold: float = 0.5, min_speech_ms: int = 250):
        self.threshold = threshold
        self.min_speech_ms = min_speech_ms

    def detect(self, audio: np.ndarray, sample_rate: int) -> list[VADRegion]:
        """Detect speech regions in audio array."""

    def has_speech(self, audio: np.ndarray, sample_rate: int) -> bool:
        """Check if audio contains any speech."""
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `PREPROCESSING_WORKER_CONCURRENCY` | int | Number of worker instances | `1` |
| `VAD_THRESHOLD` | float | Silero VAD speech threshold | `0.5` |
| `VAD_MIN_SPEECH_MS` | int | Minimum speech region duration | `250` |
| `LOUDNORM_TARGET_LUFS` | float | Target loudness | `-23.0` |
| `LOUDNORM_TP` | float | Target true peak | `-2.0` |
| `CHAIN_TIMEOUT_S` | int | Max processing time per chunk | `3` |
| `DEEPFILTER_ENABLED` | bool | Enable DeepFilterNet | `true` |

**Third-Party Integration Contracts:**
- Valkey (S03): Stream consumer for `audio.chunk`
- MinIO (S14): Download chunk, upload processed output
- ffmpeg: System binary for resampling/loudnorm
- DeepFilterNet: Python library for denoise
- Silero VAD: ONNX model for voice activity detection

**Version Pins:**
- ffmpeg >= 6.0
- DeepFilterNet >= 3.0
- silero-vad >= 5.0
- numpy >= 1.26.0

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T17.1 | U | `pytest tests/test_preprocessing.py::test_output_format -v` | Output is 16kHz mono regardless of input format/rate |
| T17.2 | V | `pytest tests/test_preprocessing.py::test_loudnorm -v` | Loudnorm brings quiet sample within target LUFS range |
| T17.3 | V | `pytest tests/test_preprocessing.py::test_silence_zero_speech -v` | Pure silence produces zero speech regions |
| T17.4 | V | `pytest tests/test_preprocessing.py::test_hvac_noise -v` | HVAC-only noise produces zero speech regions |
| T17.5 | V | `pytest tests/test_preprocessing.py::test_quiet_speech_retained -v` | Quiet-but-real speech is retained, not gated out |
| T17.6 | V | `pytest tests/test_preprocessing.py::test_denoise_snr -v` | DeepFilterNet improves SNR on noisy sample |
| T17.7 | P | `pytest tests/test_preprocessing.py::test_chain_latency -v` | Chain processes 30s chunk in < 3s |

**Test Case Details (Given/When/Then):**

**T17.1 — Output is 16kHz mono**
- **Given:** audio fixtures at 8kHz, 44.1kHz, 48kHz, stereo and mono
- **When:** each is processed through the chain
- **Then:** output is 16kHz mono float32 PCM for all inputs

**T17.2 — Loudnorm brings quiet sample within target LUFS**
- **Given:** a deliberately quiet audio sample (-40 LUFS)
- **When:** processed through the loudnorm stage
- **Then:** output LUFS is within target range (-23 ± 2 LUFS)

**T17.3 — Pure silence produces zero speech regions (critical assertion)**
- **Given:** a 30-second chunk of digital silence (all zeros)
- **When:** processed through the VAD stage
- **Then:** `vad_regions` is empty; `speech_ratio=0.0`; `has_speech=false`

**T17.4 — HVAC noise produces zero speech regions**
- **Given:** a 30-second chunk of steady HVAC hum (no speech)
- **When:** processed through denoise + VAD
- **Then:** `vad_regions` is empty; `speech_ratio=0.0`; `has_speech=false`

**T17.5 — Quiet speech is retained (false-negative check)**
- **Given:** a 30-second chunk with quiet but intelligible speech
- **When:** processed through the full chain
- **Then:** speech regions detected; `has_speech=true`; speech is not gated out

**T17.6 — DeepFilterNet improves SNR**
- **Given:** a noisy audio sample with known SNR (from S04 corpus)
- **When:** processed through DeepFilterNet denoise
- **Then:** output SNR is improved by ≥ 5 dB compared to input

**T17.7 — Chain latency under 3s**
- **Given:** a 30-second audio chunk
- **When:** processed through the full chain
- **Then:** total processing time < 3 seconds (real-time factor < 0.1)

**Verification Commands:**
```bash
uv run pytest tests/test_preprocessing.py -v -k "S17" && \
uv run mypy --strict src/workers/preprocessing_worker.py src/services/audio_chain/ && \
uv run ruff check src/workers/preprocessing_worker.py src/services/audio_chain/
```

**Exit Criteria:**
- [ ] T17.1 passes — 16kHz mono output
- [ ] T17.2 passes — loudnorm within target LUFS
- [ ] T17.3 passes — silence produces zero speech regions (critical)
- [ ] T17.4 passes — HVAC noise produces zero speech regions
- [ ] T17.5 passes — quiet speech retained
- [ ] T17.6 passes — SNR improved by denoise
- [ ] T17.7 passes — chain latency < 3s

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- ffmpeg `loudnorm` two-pass is more accurate but slower — single-pass acceptable for real-time
- DeepFilterNet loads ~200MB model — first invocation slower due to model loading
- Silero VAD ONNX runtime has startup overhead — keep process alive between chunks
- `pipe:1` ffmpeg output must be read completely — partial read causes SIGPIPE
- Chunks with no speech must still be emitted (for completeness tracking)

**Fallback Instructions:**
- If DeepFilterNet OOM: fall back to ffmpeg-only denoise (anlmdn filter)
- If Silero VAD fails: assume all speech; emit full chunk as single VAD region
- If chain exceeds timeout: log warning, emit chunk anyway (best effort)
- If ffmpeg unavailable: fail fast with clear error (hard dependency)

**Rollback Procedure:**
- Stop preprocessing worker: `docker compose stop preprocessing`
- No database migrations
- Chunks remain in `audio.chunk` stream for reprocessing
- Feature flag: `PREPROCESSING_ENABLED=false` skips chain (emergency only — increases hallucination risk)

---

### 9. Observability (if applicable)

**Metrics Added:**
- `preprocessing_chunk_total`: counter of chunks processed (labels: has_speech, success=true/false)
- `preprocessing_latency_ms`: histogram of chain processing time
- `preprocessing_speech_ratio`: histogram of speech ratios
- `preprocessing_lufs_before`: histogram of input loudness
- `preprocessing_lufs_after`: histogram of output loudness
- `preprocessing_snr_before`: histogram of input SNR
- `preprocessing_snr_after`: histogram of output SNR
- `preprocessing_vad_regions_count`: histogram of VAD regions per chunk
- `preprocessing_denoise_enabled`: gauge of denoise status

**Tracing/Logging:**
- Span: `preprocessing.chain` with attributes (session_id, sequence, latency_ms)
- Span: `preprocessing.resample` with attributes (input_rate, output_rate)
- Span: `preprocessing.denoise` with attributes (method, snr_before, snr_after)
- Span: `preprocessing.vad` with attributes (regions_count, speech_ratio)
- Log: INFO on chunk processed
- Log: WARN on chain timeout
- Log: ERROR on processing failure

**Alerts:**
- Speech ratio consistently 0 for non-silent audio: VAD threshold too high
- Chain latency > 5s: performance degradation
- Denoise failure rate > 10%: DeepFilterNet issue

---

### 10. Exit Checklist

- [ ] All tests pass (T17.1–T17.7)
- [ ] Silence and steady noise removed before ASR
- [ ] Real quiet speech preserved
- [ ] Chain processes 30s chunk in < 3s
- [ ] VAD map emitted with processed audio
- [ ] Worker consumes `audio.chunk` stream
- [ ] Processed output written to `lis-audio` or `lis-generated`

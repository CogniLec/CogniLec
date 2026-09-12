# S19 — ASR Worker (Primary Model)
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Run faster-whisper ASR with wav2vec2 forced alignment to produce word-level timestamped transcripts, persist utterances to DB-1, and enforce the NFR-R3 durability gate before downstream processing.

**Component Boundaries:**
- **Allowed:** `src/workers/asr_worker.py`, `src/services/asr/`, `tests/test_asr_worker.py`, `tests/fixtures/audio/`
- **Off-limits:** Diarisation (S20), preprocessing (S17), embedding (S25), segmentation (S30)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| faster-whisper | 1.1.x | ASR inference (CTranslate2 backend) |
| CTranslate2 | 4.x | Quantized model runtime |
| wav2vec2 | 0.12.x | Forced alignment for word timestamps |
| torch | 2.5.x | Model runtime |
| SQLAlchemy | 2.0.52 | DB persistence |
| asyncpg | 0.31.0 | PG driver |

---

### 2. State Machine & Domain Schemas

**ASR Worker State:**
```
IDLE → LOADING_MODEL → READY → PROCESSING → IDLE
                              ↓
                           FAILED
```

**Utterance Schema:**
```python
# src/services/asr/models.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

class WordTimestamp(BaseModel):
    word: str
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)

class Utterance(BaseModel):
    session_id: UUID
    subject_id: UUID
    sequence: int  # utterance sequence within session
    text: str
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    words: list[WordTimestamp]
    embed_model_ver: str  # from config
    speaker_tag: str | None = None  # set by S20 diarisation
    created_at: datetime

class ASRResult(BaseModel):
    session_id: UUID
    utterances: list[Utterance]
    total_duration_ms: int
    processing_time_ms: int
    real_time_factor: float  # processing_time / total_duration
    model_name: str
    model_quantization: str
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Implement faster-whisper model loading (large-v3-turbo FP16 or large-v3 int8) | Model loads and serves |
| 2 | Implement transcription with word-level timestamps | Word timestamps present and monotonically increasing |
| 3 | Implement wav2vec2 forced alignment | Word-level alignment correct |
| 4 | Implement utterance persistence to `utterances` table | Utterances persisted with correct fields |
| 5 | Implement session state transition `recording → transcribed` | Session reaches `transcribed` after commit |
| 6 | Implement NFR-R3 durability gate | Downstream flow rejected if not `transcribed` |
| 7 | Implement crash recovery (skip already-transcribed chunks) | Restart does not reprocess |
| 8 | Benchmark real-time factor | RTF < 1.0 (NFR-P1) |

**Atomic Sub-tasks:**
1. faster-whisper model loading and configuration
2. Transcription pipeline with word timestamps
3. wav2vec2 forced alignment
4. Utterance persistence
5. Session state transition
6. NFR-R3 durability gate
7. Crash recovery

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Model fails to load | Fail fast; log error; alert |
| OOM during transcription | Reduce batch size; retry once |
| Chunks arrive out of order | Buffer and reorder before transcription |
| Worker killed mid-session | On restart, skip chunks with existing utterances |
| Empty audio (no speech) | Emit empty utterance list; still transition to `transcribed` |
| Very long chunk (>5min) | Split into sub-chunks for processing |
| Alignment fails on word | Fall back to segment-level timestamps |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Worker pattern: Valkey Stream consumer for `audio.processed`
- Repository pattern: `UtteranceRepository` for DB persistence
- Gate pattern: NFR-R3 assertion at downstream trigger
- Recovery pattern: idempotent chunk processing

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`asr_worker.py`, `faster_whisper_service.py`)
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
```yaml
Stream: audio.processed
Consumer Group: asr
Consumer: asr-worker-1

XREADGROUP GROUP asr asr-worker-1 COUNT 5 BLOCK 10000 STREAMS audio.processed >

# Message fields:
{
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "sequence": "0",
    "object_key": "550e8400.../processed/00000.wav",
    "has_speech": "true",
    "speech_ratio": "0.72"
}
```

**Utterance Database Schema:**
```sql
CREATE TABLE utterances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    subject_id UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    sequence INT NOT NULL,
    text TEXT NOT NULL,
    start_ms INT NOT NULL CHECK (start_ms >= 0),
    end_ms INT NOT NULL CHECK (end_ms >= 0),
    confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    words JSONB NOT NULL DEFAULT '[]',
    embed_model_ver VARCHAR(50) NOT NULL,
    speaker_tag VARCHAR(10),  -- set by S20, NULL initially
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, sequence)
);

CREATE INDEX idx_utterances_session ON utterances(session_id);
CREATE INDEX idx_utterances_subject ON utterances(subject_id);
```

**NFR-R3 Gate Assertion:**
```python
# src/services/nfr_r3_gate.py
class NFR_R3_Gate:
    async def assert_transcribed(self, session_id: UUID) -> bool:
        """
        Assert session is in 'transcribed' status.
        Raises ValueError if not.
        NFR-R3: Transcript committed before downstream starts.
        """
        session = await self.session_repo.get_by_id(session_id)
        if session.status != SessionStatus.TRANSCRIBED:
            raise ValueError(
                f"NFR-R3 violated: session {session_id} "
                f"status is '{session.status}', expected 'transcribed'"
            )
        return True
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `ASR_MODEL_NAME` | string | Model ID | `Systran/faster-whisper-large-v3-turbo` |
| `ASR_MODEL_QUANTIZATION` | string | Quantization | `float16` |
| `ASR_DEVICE` | string | Compute device | `cuda` |
| `ASR_COMPUTE_TYPE` | string | CTranslate2 compute type | `float16` |
| `ASR_BEAM_SIZE` | int | Beam size | `5` |
| `ASR_LANGUAGE` | string | Language hint | `en` |
| `ASR_WORD_timestamps` | bool | Enable word timestamps | `true` |
| `ASR_ALIGNMENT_MODEL` | string | wav2vec2 alignment model | `jonatasgrosman/wav2vec2-large-xlsr-53-english` |
| `ASR_MAX_CHUNK_DURATION_S` | int | Max chunk duration | `30` |
| `EMBED_MODEL_VER` | string | Embedding model version | `qwen3-0.6b-v1` |

**Third-Party Integration Contracts:**
- Valkey (S03): Stream consumer for `audio.processed`
- PostgreSQL (S07): Utterance persistence
- MinIO (S14): Download processed audio
- faster-whisper: ASR inference
- wav2vec2: Forced alignment

**Version Pins:**
- faster-whisper >= 1.1.0
- CTranslate2 >= 4.0
- torch >= 2.5.0
- SQLAlchemy >= 2.0.52

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T19.1 | V | `pytest tests/test_asr_worker.py::test_wer_benchmark -v` | WER on held-out set within tolerance of S06 benchmark |
| T19.2 | I | `pytest tests/test_asr_worker.py::test_word_timestamps -v` | Word-level timestamps present and monotonically increasing |
| T19.3 | I | `pytest tests/test_asr_worker.py::test_utterance_persistence -v` | Utterances persisted with confidence, correct session/subject, embed_model_ver |
| T19.4 | I | `pytest tests/test_asr_worker.py::test_session_transcribed -v` | Session reaches `transcribed` only after commit |
| T19.5 | I | `pytest tests/test_asr_worker.py::test_crash_recovery -v` | Worker killed mid-session → on restart, already-transcribed chunks not reprocessed |
| T19.6 | P | `pytest tests/test_asr_worker.py::test_real_time_factor -v` | Real-time factor < 1.0 (NFR-P1) |
| T19.7 | I | `pytest tests/test_asr_worker.py::test_nfr_r3_gate -v` | Downstream flow rejected if session status is not `transcribed` |

**Test Case Details (Given/When/Then):**

**T19.1 — WER on held-out set within tolerance**
- **Given:** the S05 held-out test set with known ground truth
- **When:** ASR processes the held-out set
- **Then:** WER is within ±2% of the S06 benchmark result

**T19.2 — Word-level timestamps present and monotonically increasing**
- **Given:** a processed audio chunk with speech
- **When:** ASR produces utterances
- **Then:** each utterance has `words` list; word `start_ms` < `end_ms`; words are monotonically ordered

**T19.3 — Utterances persisted with correct fields**
- **Given:** ASR produces utterances for a session
- **When:** utterances are persisted to DB-1
- **Then:** each utterance has `session_id`, `subject_id`, `confidence`, `embed_model_ver`, `words` JSONB

**T19.4 — Session reaches transcribed only after commit**
- **Given:** a session in `recording` status with all chunks processed
- **When:** the last utterance is committed to DB
- **Then:** session status transitions to `transcribed`; not before

**T19.5 — Crash recovery skips already-transcribed chunks**
- **Given:** a session with chunks 0-9 already transcribed
- **When:** the worker restarts and re-processes the stream
- **Then:** chunks 0-9 are skipped; only new chunks are processed

**T19.6 — Real-time factor < 1.0 (NFR-P1)**
- **Given:** a 30-second audio chunk
- **When:** ASR processes the chunk on GPU
- **Then:** processing time < 30 seconds (RTF < 1.0)

**T19.7 — NFR-R3 gate rejects non-transcribed sessions**
- **Given:** a session in `recording` status
- **When:** a downstream flow attempts to trigger
- **Then:** `NFR_R3_Gate.assert_transcribed()` raises `ValueError`; flow does not start

**Verification Commands:**
```bash
uv run pytest tests/test_asr_worker.py -v -k "S19" && \
uv run mypy --strict src/workers/asr_worker.py src/services/asr/ && \
uv run ruff check src/workers/asr_worker.py src/services/asr/
```

**Exit Criteria:**
- [ ] T19.1 passes — WER within tolerance
- [ ] T19.2 passes — word-level timestamps
- [ ] T19.3 passes — utterances persisted correctly
- [ ] T19.4 passes — session reaches `transcribed` after commit
- [ ] T19.5 passes — crash recovery works
- [ ] T19.6 passes — real-time factor < 1.0 (NFR-P1)
- [ ] T19.7 passes — NFR-R3 gate enforced
- [ ] A real lecture becomes a durable, word-timestamped transcript in DB-1

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- faster-whisper CTranslate2 requires specific model formats — must use compatible model ID
- wav2vec2 alignment can fail on very short utterances — fall back to segment timestamps
- GPU OOM with large-v3 at float16 — consider int8_float16 quantization (ADR-017)
- Word timestamps may drift from audio if VAD regions are imprecise
- `embed_model_ver` must be set from config, not hardcoded

**Fallback Instructions:**
- If GPU OOM: switch to `int8_float16` quantization
- If alignment fails: use segment-level timestamps (less precise but functional)
- If model unavailable: fail fast; do not attempt alternative model without explicit config
- If DB persistence fails: log error; chunk remains in stream for retry

**Rollback Procedure:**
- Stop ASR worker: `docker compose stop asr`
- Utterances remain in DB (no rollback needed)
- Chunks remain in `audio.processed` stream for reprocessing
- Feature flag: `ASR_WORKER_ENABLED=false` stops processing (chunks queue)

---

### 9. Observability (if applicable)

**Metrics Added:**
- `asr_chunks_processed_total`: counter of chunks processed (labels: success=true/false)
- `asr_real_time_factor`: histogram of real-time factors
- `asr_latency_ms`: histogram of per-chunk processing time
- `asr_utterances_total`: counter of utterances produced
- `asr_wer`: gauge of WER on evaluation set
- `asr_model_load_duration_seconds`: gauge of model load time
- `asr_gpu_memory_used_bytes`: gauge of GPU memory usage

**Tracing/Logging:**
- Span: `asr.transcribe_chunk` with attributes (session_id, sequence, rtf, utterances_count)
- Span: `asr.align_words` with attributes (utterance_id, words_count)
- Span: `asr.persist_utterances` with attributes (session_id, count)
- Log: INFO on chunk processed with RTF
- Log: WARN on alignment fallback
- Log: ERROR on OOM, model load failure

**Alerts:**
- RTF > 1.5 sustained: GPU performance issue
- OOM errors > 3 in 5 minutes: model too large for VRAM
- WER > 25% on eval set: model degradation

---

### 10. Exit Checklist

- [ ] All tests pass (T19.1–T19.7)
- [ ] faster-whisper model loaded at production quantization
- [ ] Word-level timestamps produced via wav2vec2 alignment
- [ ] Utterances persisted to DB-1 with all required fields
- [ ] Session transitions to `transcribed` after commit
- [ ] NFR-R3 durability gate enforced
- [ ] Crash recovery skips already-transcribed chunks
- [ ] Real-time factor < 1.0 (NFR-P1)
- [ ] Real lecture becomes durable transcript in DB-1

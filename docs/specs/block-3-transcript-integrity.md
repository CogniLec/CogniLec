# BLOCK 3 — Transcript Integrity
## Specification Document: S21–S24

**Implements:** SRS v2.0 §3.1 · FR-2.1, FR-2.2, FR-2.3, FR-2.15, FR-7.8, NFR-R4, NFR-R5, NFR-R6, NFR-P3
**Block Owner:** ML + Backend
**Estimate:** 4 stages, ~2 weeks serial
**Gate:** None (Block 3 is not a gate; Block 4 downstream is gated at S29)

---

## Table of Contents

1. [Block Overview](#block-overview)
2. [S21 — Dual-ASR Ensemble](#s21--dual-asr-ensemble)
3. [S22 — Hallucination Detection](#s22--hallucination-detection)
4. [S23 — Session Lifecycle State Machine](#s23--session-lifecycle-state-machine)
5. [S24 — Transcript Read API & Client View](#s24--transcript-read-api--client-view)
6. [Cross-Stage Contracts](#cross-stage-contracts)
7. [Appendix A — Full Migration Plan](#appendix-a--full-migration-plan)
8. [Appendix B — Config Keys Added](#appendix-b--config-keys-added)
9. [Appendix C — Observability Dashboard](#appendix-c--observability-dashboard)

---

## Block Overview

Block 3 transforms the raw ASR transcript produced by Block 2 (S19–S20) into a **validated, hallucination-filtered, queryable** transcript with an auditable integrity trail. It is the first block that produces user-visible output.

**Preconditions:**
- S20 gate passed: end-to-end ingestion spine works on real audio
- `utterances` table populated with raw ASR output (text, timestamps, confidence, speaker_tag)
- `asr_agreement` column exists on `utterances` (already DDL-ready from S09 migration, currently NULL)
- `is_relevant` and `filter_reason` columns exist on `utterances` (already DDL-ready, currently NULL)
- Session model has `SessionStatus` enum with `created → recording → transcribed → processing → complete | failed`
- `notes_ready` flag exists on `sessions` (currently default False)

**What this block does NOT do:**
- Does not generate embeddings (S25–S26)
- Does not assign topics (S28–S30)
- Does not synthesize notes (S41–S46)
- Does not implement multi-user auth (S72)

---

## S21 — Dual-ASR Ensemble

### 1. Stage Identity

| Field | Value |
|-------|-------|
| **ID** | S21 |
| **Name** | Dual-ASR Ensemble |
| **Block** | B3 — Transcript Integrity |
| **Owner** | ML |
| **Estimate** | 3 days |
| **Deps** | S20, S06 |
| **SRS** | v2.0 §3.1 · SR-01 |

### 2. Context

The primary ASR model (whisper-large-v3-turbo, locked at S06) produces high-quality transcripts but can hallucinate in silence or produce degenerate repetitions. A second ASR model provides an independent signal: when both models agree on text content, confidence is high; when they diverge, the utterance is suspect.

The secondary model is the second-place finisher from the S06 bake-off. Based on `scripts/s06_asr_bakeoff.py:45`, this is `canary-qwen-2.5b` (NVIDIA Canary, 25B params, int8_float16 via faster-whisper) or `parakeet-tdt-1.1b` (NeMo backend). The exact model is configured in `config/models.yaml`.

This stage runs the secondary model on every completed session, aligns its output to the primary's utterances by timestamp, computes a per-utterance agreement score, and persists it to the existing `utterances.asr_agreement` column.

### 3. Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| S20 | Upstream stage | GATE — transcript must exist before dual-ASR can run |
| S06 | Model lock | Secondary model ID and quantization frozen |
| `faster-whisper` | External lib | CTranslate2 backend for Whisper-family models |
| `config/models.yaml` | Config | Must add `secondary_asr_model` key |
| GPU host | Infra | 4GB VRAM shared; secondary model must fit alongside primary or run sequentially |

### 4. Requirements Traced

| SRS ID | Requirement | How S21 implements |
|--------|-------------|---------------------|
| SR-01 | ASR accuracy validated | Dual-ASR agreement is a proxy for accuracy; low agreement → suspect utterance |
| v2.0 §3.1 | Transcript quality assurance | Cross-model agreement is the primary quality signal |

### 5. Interface Contracts

#### 5.1 Config Keys Added

```yaml
# config/models.yaml — additions
secondary_asr_model: "nvidia/canary-25b-12b-pt"  # or parakeet-tdt-1.1b
secondary_asr_engine: "faster_whisper"             # "faster_whisper" | "nemo"
secondary_asr_compute_type: "int8_float16"
secondary_asr_device: "cuda"
secondary_asr_beam_size: 5
```

```python
# src/core/config.py — additions to Settings class
SECONDARY_ASR_MODEL: str = "nvidia/canary-25b-12b-pt"
SECONDARY_ASR_ENGINE: str = "faster_whisper"
SECONDARY_ASR_COMPUTE_TYPE: str = "int8_float16"
SECONDARY_ASR_BEAM_SIZE: int = 5
DUAL_ASR_ENABLED: bool = True
AGREEMENT_THRESHOLD: float = 0.5  # below this → flag for hallucination detection
```

#### 5.2 Worker Interface

```
File: src/workers/dual_asr_worker.py
```

```python
class DualASRWorker:
    """Runs secondary ASR model on completed sessions and computes agreement."""

    async def process_session(self, session_id: UUID) -> DualASRResult:
        """
        1. Load primary utterances from DB (already persisted by S19)
        2. Load audio from lis-audio bucket (or reassemble from chunks)
        3. Run secondary ASR model → get utterance list with timestamps
        4. Align secondary utterances to primary utterances by timestamp IoU
        5. Compute per-utterance agreement score
        6. Persist asr_agreement to utterances table
        7. Return DualASRResult with summary stats
        """

    def align_utterances(
        self,
        primary: list[Utterance],
        secondary: list[SecondaryUtterance],
        iou_threshold: float = 0.3,
    ) -> list[AlignmentPair]:
        """Align primary and secondary utterances by timestamp overlap (IoU)."""

    def compute_agreement(
        self,
        primary_text: str,
        secondary_text: str,
    ) -> float:
        """Compute normalized agreement score [0.0, 1.0] using token-level F1 or WER-inverted."""
```

#### 5.3 Data Structures

```python
# src/workers/dual_asr_worker.py

@dataclass
class SecondaryUtterance:
    text: str
    start_ms: int
    end_ms: int
    confidence: float

@dataclass
class AlignmentPair:
    primary_id: UUID
    secondary_text: str | None  # None if no match found
    iou: float                  # intersection-over-union of time windows
    agreement: float            # text agreement score [0.0, 1.0]

@dataclass
class DualASRResult:
    session_id: UUID
    utterances_total: int
    utterances_aligned: int
    mean_agreement: float
    min_agreement: float
    duration_ms: int            # wall-clock time for dual ASR
```

#### 5.4 Agreement Score Algorithm

```
agreement(primary_text, secondary_text) → float:
    1. Normalize both texts (lowercase, strip punctuation, collapse whitespace)
    2. Tokenize into words
    3. Compute token-level F1 score:
       - precision = |intersection| / |secondary_tokens|
       - recall = |intersection| / |primary_tokens|
       - f1 = 2 * precision * recall / (precision + recall)
    4. Return f1 (range [0.0, 1.0])
    5. If secondary utterance not aligned (no IoU match): return NULL (not 0.0)
```

#### 5.5 Alignment Algorithm

```
align_utterances(primary[], secondary[], iou_threshold=0.3) → AlignmentPair[]:
    For each primary utterance p:
        Find secondary utterance s maximizing IoU(p, s):
            IoU = overlap_ms / union_ms
            overlap_ms = max(0, min(p.end, s.end) - max(p.start, s.start))
            union_ms = (p.end - p.start) + (s.end - s.start) - overlap_ms
        If max IoU >= iou_threshold:
            Create AlignmentPair(p.id, s.text, iou, agreement(p.text, s.text))
        Else:
            Create AlignmentPair(p.id, NULL, 0.0, NULL)
    Return pairs
```

#### 5.6 SQL DDL

No new tables. Updates existing column:

```sql
-- Already exists from S09 migration (c58ea6212bc5):
-- asr_agreement DOUBLE PRECISION (nullable)
-- No migration needed for S21.
```

### 6. Implementation Notes

**GPU Memory Management:**
- Primary model (whisper-large-v3-turbo, FP16) uses ~3GB VRAM
- Secondary model (canary-25b, int8) uses ~2.5GB VRAM
- **Cannot run both simultaneously on 4GB VRAM.** Must run sequentially:
  1. Primary ASR completes (S19)
  2. Primary model unloaded from GPU
  3. Secondary model loaded
  4. Secondary ASR runs (S21)
  5. Secondary model unloaded
- Alternative: run secondary model on CPU if GPU memory is exhausted (slower but functional)

**Audio Retrieval:**
- Audio chunks stored in `lis-audio` bucket (S14)
- Reassemble chunks by `(session_id, seq)` order
- Convert to 16kHz mono WAV for secondary model input
- Cache reassembled audio in `lis-generated` bucket to avoid repeated reassembly

**Failure Handling:**
- If secondary model fails to load → proceed with primary alone, `asr_agreement = NULL` for all utterances (T21.3)
- If secondary model OOM → fall back to CPU inference
- If secondary model times out (> 2× primary duration) → abort, set NULL
- Never block the primary transcript on secondary failure

**Feature Flag:**
```python
# src/core/config.py
DUAL_ASR_ENABLED: bool = True  # set False to skip secondary ASR entirely
```

### 7. Test Specification

| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T21.1 | I | A session with 50 utterances from primary ASR; secondary model available | DualASRWorker.process_session() runs | Every utterance has `asr_agreement` set (non-NULL); agreement scores are in [0.0, 1.0]; `DualASRResult.utterances_aligned == 50` |
| T21.2 | V | S05 labelled set (ground truth + primary ASR + secondary ASR) | Compute agreement for each utterance; compute WER for each utterance | Pearson correlation between agreement and WER is negative (r < -0.3, p < 0.05) — low agreement correlates with high error |
| T21.3 | I | Secondary model binary is missing or fails to load | DualASRWorker.process_session() runs | Pipeline completes; all utterances have `asr_agreement = NULL`; session status reaches `transcribed`; no exception raised |
| T21.4 | P | 60-minute session with ~600 utterances | Time dual ASR from start to finish | Total dual ASR time < NFR-P3 budget (configurable, default 300s) |

### 8. Observability

| Signal | Type | Description |
|--------|------|-------------|
| `dual_asr.session.duration_ms` | Histogram | Wall-clock time per session for dual ASR |
| `dual_asr.utterance.agreement` | Histogram | Distribution of agreement scores across utterances |
| `dual_asr.utterance.unaligned_count` | Counter | Number of utterances with no secondary match (IoU < threshold) |
| `dual_asr.model.load_success` | Counter | Secondary model load attempts and outcomes |
| `dual_asr.model.oom_fallback` | Counter | Number of OOM fallbacks to CPU |
| Span: `dual_asr.process_session` | Trace span | Wraps entire dual ASR processing per session |

### 9. Rollback

- **Feature flag:** Set `DUAL_ASR_ENABLED=False` in `.env` to skip secondary ASR entirely
- **Database:** No migration to revert (column already exists)
- **Code:** Remove `src/workers/dual_asr_worker.py` and its registration in the worker orchestrator
- **Config:** Remove `secondary_asr_*` keys from `config/models.yaml`
- **Impact:** Utterances retain `asr_agreement = NULL`; no downstream stage breaks (S22 treats NULL agreement as "no signal")

### 10. Exit Checklist

- [ ] Every utterance in a processed session carries an `asr_agreement` score or explicit NULL
- [ ] Secondary model runs on GPU (or CPU fallback) without blocking primary transcript
- [ ] Agreement score correlates negatively with WER on S05 labelled set
- [ ] Pipeline degrades gracefully when secondary model is unavailable
- [ ] Dual ASR completes within NFR-P3 time budget
- [ ] All tests T21.1–T21.4 pass
- [ ] Observability signals emitted and visible in trace/metrics dashboard

---

## S22 — Hallucination Detection

### 1. Stage Identity

| Field | Value |
|-------|-------|
| **ID** | S22 |
| **Name** | Hallucination Detection |
| **Block** | B3 — Transcript Integrity |
| **Owner** | ML |
| **Estimate** | 3 days |
| **Deps** | S21 |
| **SRS** | SR-01 · FR-2.2 · FR-2.15 |

### 2. Context

Whisper-family models have well-documented failure modes that produce hallucinated text:
1. **Cross-model disagreement:** One model emits text where the other emits silence
2. **Repetition loops:** N-gram cycles characteristic of Whisper degeneration
3. **VAD contradiction:** Text present in a region that Silero VAD (S17) marked as speechless

This stage implements three independent detectors, runs them on every utterance, and flags suspect utterances as `is_relevant=false, filter_reason='asr_hallucination'`. Flagged utterances are **soft-deleted** (never removed from the database), satisfying FR-2.15 (retain for audit).

### 3. Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| S21 | Upstream stage | Provides `asr_agreement` signal for cross-model detector |
| S17 | VAD map | Provides speech/silence regions for VAD contradiction detector |
| S04 | Audio corpus | Reference set for false-positive rate measurement |

### 4. Requirements Traced

| SRS ID | Requirement | How S22 implements |
|--------|-------------|---------------------|
| SR-01 | ASR quality validated | Hallucination rate measured on S04 corpus |
| FR-2.2 | Transcript quality | Three detectors catch canonical Whisper failures |
| FR-2.15 | Soft delete, never remove | Flagged utterances: `is_relevant=false, filter_reason='asr_hallucination'` |

### 5. Interface Contracts

#### 5.1 Detector Interfaces

```
File: src/ml/hallucination.py
```

```python
class HallucinationDetector:
    """Orchestrates three independent hallucination detectors."""

    def __init__(self, config: HallucinationConfig):
        self.cross_model = CrossModelDetector(config.agreement_threshold)
        self.repetition = RepetitionDetector(config.max_repeat_ngram, config.max_repeat_count)
        self.vad_contradiction = VADContradictionDetector(config.vad_margin_ms)

    def detect(
        self,
        utterance: Utterance,
        vad_regions: list[VADRegion] | None = None,
    ) -> HallucinationResult:
        """Run all three detectors; return combined result."""
```

```python
# src/ml/hallucination.py

@dataclass
class HallucinationResult:
    is_hallucination: bool
    detectors_fired: list[str]    # ["cross_model", "repetition", "vad_contradiction"]
    confidence: float             # combined confidence [0.0, 1.0]
    details: dict[str, Any]       # detector-specific details for audit

@dataclass
class VADRegion:
    start_ms: int
    end_ms: int
    is_speech: bool

@dataclass
class HallucinationConfig:
    agreement_threshold: float = 0.5     # below this → cross-model fires
    max_repeat_ngram: int = 3            # n-gram size for repetition detection
    max_repeat_count: int = 3            # max allowed repetitions
    vad_margin_ms: int = 200             # tolerance around VAD boundaries
    min_utterance_length_ms: int = 500   # ignore very short utterances
```

#### 5.2 Detector Algorithms

**Detector A — Cross-Model Disagreement:**
```
cross_model_detector(utterance) → fires if:
    utterance.asr_agreement IS NOT NULL
    AND utterance.asr_agreement < agreement_threshold
    AND utterance.text.strip() != ""
Rationale: one model produced text, the other did not (or produced very different text).
```

**Detector B — Repetition Detector:**
```
repetition_detector(utterance) → fires if:
    tokens = utterance.text.lower().split()
    for n in [3, 4, 5]:  # check 3-gram, 4-gram, 5-gram
        ngrams = sliding_window(tokens, n)
        for ngram in ngrams:
            count = ngrams.count(ngram)
            if count >= max_repeat_count:
                return True with detail {"ngram": ngram, "count": count, "n": n}
    return False
```

**Detector C — VAD Contradiction:**
```
vad_contradiction_detector(utterance, vad_regions) → fires if:
    utterance duration > min_utterance_length_ms
    AND utterance overlaps with a VAD region where is_speech == False
    AND the overlap covers > 50% of the utterance duration
    (with vad_margin_ms tolerance on boundaries)
```

#### 5.3 Config Keys Added

```python
# src/core/config.py — additions
HALLUCINATION_DETECTION_ENABLED: bool = True
HALLUCINATION_AGREEMENT_THRESHOLD: float = 0.5
HALLUCINATION_MAX_REPEAT_NGRAM: int = 3
HALLUCINATION_MAX_REPEAT_COUNT: int = 3
HALLUCINATION_VAD_MARGIN_MS: int = 200
HALLUCINATION_MIN_UTTERANCE_LENGTH_MS: int = 500
```

#### 5.4 SQL DDL

No new tables or columns. Uses existing:
- `utterances.is_relevant` (BOOLEAN, nullable, default NULL)
- `utterances.filter_reason` (VARCHAR(100), nullable, default NULL)

```sql
-- No migration needed for S22.
-- Flagged utterances are updated:
UPDATE utterances
SET is_relevant = false,
    filter_reason = 'asr_hallucination'
WHERE id = :utterance_id;
```

#### 5.5 Filter Reason Values

| Value | Meaning |
|-------|---------|
| `asr_hallucination` | Any of the three detectors fired |
| `asr_hallucination_cross_model` | Cross-model disagreement detector fired |
| `asr_hallucination_repetition` | Repetition detector fired |
| `asr_hallucination_vad` | VAD contradiction detector fired |

Multiple detectors may fire on the same utterance; the filter_reason stores the primary (first-firing) detector. All detectors that fired are recorded in `outlier_score` as a bitmask or in a separate audit log.

### 6. Implementation Notes

**Orchestration:**
- Hallucination detection runs **after** dual ASR (S21) completes for a session
- Called by the same worker or as a post-processing step
- Iterates over all utterances in the session

**False-Positive Guard:**
- Real speech can have low cross-model agreement (accents, overlapping speech)
- The repetition detector must tolerate intentional repetition (e.g., "any questions? any questions?")
- VAD contradiction requires the utterance to be >50% within a silence region (not just touching)

**Audit Trail:**
- Every flagged utterance records which detector(s) fired
- `outlier_score` can store a composite score (e.g., sum of detector confidences)
- Filtered utterances are retained in DB with `is_relevant=false` for manual review

**Failure Handling:**
- If VAD regions are unavailable (S17 not run or failed), VAD contradiction detector is skipped
- If `asr_agreement` is NULL (dual ASR not run), cross-model detector is skipped
- Detectors are independent; one failing does not affect others
- Never raise exceptions; log warnings and proceed

### 7. Test Specification

| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T22.1 | V | 60 seconds of pure silence audio (no speech) fed through primary ASR → produces hallucinated utterances (the canonical Whisper failure) | HallucinationDetector.detect() runs on each utterance | Every hallucinated utterance is flagged `is_relevant=false, filter_reason='asr_hallucination'`; zero utterances retained as relevant |
| T22.2 | V | A 30-second audio clip with a deliberately repeated phrase ("the process is the process is the process is the process") | RepetitionDetector runs on the resulting utterance | Detector fires; `is_relevant=false, filter_reason='asr_hallucination_repetition'` |
| T22.3 | V | S04 real speech corpus (100 utterances of genuine lecture content) | All three detectors run | False-positive rate < 2% (at most 2 of 100 real utterances incorrectly flagged) |
| T22.4 | I | An utterance flagged by any detector | Query database | `is_relevant = false`; `filter_reason` starts with `asr_hallucination`; row exists (not deleted) |
| T22.5 | V | S04 corpus processed through full pipeline | Count flagged utterances | Hallucination rate recorded as metric in MLflow/experiment tracker |

### 8. Observability

| Signal | Type | Description |
|--------|------|-------------|
| `hallucination.total_flagged` | Counter | Total utterances flagged across all sessions |
| `hallucination.rate` | Gauge | Flagged / total utterances per session |
| `hallucination.detector.cross_model` | Counter | Cross-model detector fires |
| `hallucination.detector.repetition` | Counter | Repetition detector fires |
| `hallucination.detector.vad` | Counter | VAD contradiction detector fires |
| `hallucination.false_positive_rate` | Gauge | Measured on S04 corpus (periodic eval) |
| Span: `hallucination.detect_session` | Trace span | Per-session hallucination detection |

### 9. Rollback

- **Feature flag:** Set `HALLUCINATION_DETECTION_ENABLED=False` to skip all detectors
- **Database:** No migration to revert
- **Code:** Remove `src/ml/hallucination.py` and its invocation in the worker
- **Impact:** All utterances retain `is_relevant=NULL` (unfiltered state); downstream agents see everything

### 10. Exit Checklist

- [ ] Canonical hallucination failure (silence audio) produces zero retained utterances
- [ ] Repetition detector catches deliberate n-gram loops
- [ ] False-positive rate on real speech < 2%
- [ ] Flagged utterances are soft-deleted (row present, `is_relevant=false`)
- [ ] Hallucination rate measured and recorded as a tracked metric
- [ ] All tests T22.1–T22.5 pass
- [ ] Observability signals emitted

---

## S23 — Session Lifecycle State Machine

### 1. Stage Identity

| Field | Value |
|-------|-------|
| **ID** | S23 |
| **Name** | Session Lifecycle State Machine |
| **Block** | B3 — Transcript Integrity |
| **Owner** | Backend |
| **Estimate** | 2 days |
| **Deps** | S20 |
| **SRS** | NFR-R5, NFR-R6 |

### 2. Context

The `SessionStatus` enum already exists (`created → recording → transcribed → processing → complete | failed`), but transitions are currently scattered across worker code with no centralised guard. S16 transitions `created → recording` on first chunk. S19 transitions `recording → transcribed` on ASR completion. There is no explicit `processing` or `failed` state management.

S23 centralises all transitions in one place, enforces an exhaustive transition matrix, adds explicit failure marking (NFR-R5: never silently half-processed), and provides a retry queue for failed sessions (NFR-R4: reprocessing from retained transcript).

### 3. Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| S20 | Upstream stage | GATE — ingestion spine must work before state machine governs it |
| S16 | Chunk upload | Currently does ad-hoc status transition |
| S19 | ASR worker | Currently does ad-hoc status transition |
| `src/db/models/session.py` | Existing model | `SessionStatus` enum already defined |

### 4. Requirements Traced

| SRS ID | Requirement | How S23 implements |
|--------|-------------|---------------------|
| NFR-R5 | Failure is never silent | Explicit `failed` state; every stage failure sets it |
| NFR-R4 | Reprocessing from retained transcript | Retry queue for `failed` sessions; reprocess without re-capture |

### 5. Interface Contracts

#### 5.1 State Machine Definition

```
File: src/core/state_machine.py
```

```python
class SessionStateMachine:
    """Centralised session state transitions with guard enforcement."""

    # Valid transitions: (from_status, to_status) → guard function
    TRANSITIONS: dict[tuple[SessionStatus, SessionStatus], Callable | None] = {
        (SessionStatus.CREATED, SessionStatus.RECORDING):    None,  # first chunk uploaded
        (SessionStatus.RECORDING, SessionStatus.TRANSCRIBED): None, # ASR complete
        (SessionStatus.TRANSCRIBED, SessionStatus.PROCESSING): None, # downstream processing starts
        (SessionStatus.PROCESSING, SessionStatus.COMPLETE):   None,  # all stages done
        (SessionStatus.PROCESSING, SessionStatus.FAILED):     None,  # stage failure
        (SessionStatus.FAILED, SessionStatus.PROCESSING):     None,  # retry
        (SessionStatus.FAILED, SessionStatus.TRANSCRIBED):    None,  # re-ASR from chunks
        (SessionStatus.CREATED, SessionStatus.FAILED):        None,  # setup failure
        (SessionStatus.RECORDING, SessionStatus.FAILED):      None,  # recording failure
    }

    def validate_transition(self, from_status: SessionStatus, to_status: SessionStatus) -> bool:
        """Return True if transition is valid; raise InvalidTransition otherwise."""

    async def transition(
        self,
        session: Session,
        to_status: SessionStatus,
        db: AsyncSession,
        reason: str | None = None,
    ) -> Session:
        """Atomic transition: validate, update status, record audit event, flush."""
```

#### 5.2 Transition Matrix (Exhaustive)

| From | To | Guard | Event Emitted |
|------|----|-------|---------------|
| `created` | `recording` | First chunk uploaded | `session.recording_started` |
| `recording` | `transcribed` | ASR worker completes | `session.transcribed` |
| `transcribed` | `processing` | Downstream pipeline starts | `session.processing_started` |
| `processing` | `complete` | All stages done | `session.completed` |
| `processing` | `failed` | Any stage failure | `session.failed` with `failure_reason` |
| `failed` | `processing` | Manual retry or auto-retry | `session.retry_started` |
| `failed` | `transcribed` | Re-ASR from chunks | `session.re_asr_started` |
| `created` | `failed` | Setup failure | `session.failed` |
| `recording` | `failed` | Recording failure | `session.failed` |

**All other transitions are rejected** with `InvalidTransitionError`.

#### 5.3 Failure Marking

```python
# src/db/models/session.py — additions
class Session(Base):
    # ... existing columns ...
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

#### 5.4 Retry Queue

```python
# src/workers/retry_queue.py

class RetryQueue:
    """Valkey/Redis-based retry queue for failed sessions."""

    QUEUE_KEY = "lis:retry_queue"
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 60  # exponential backoff base

    async def enqueue(self, session_id: UUID, reason: str) -> None:
        """Add failed session to retry queue with metadata."""

    async def dequeue(self) -> RetryJob | None:
        """Pop next session eligible for retry (delay expired, retries remaining)."""

    async def mark_success(self, session_id: UUID) -> None:
        """Remove from queue on successful reprocessing."""

    async def mark_permanent_failure(self, session_id: UUID, reason: str) -> None:
        """After MAX_RETRIES, mark as permanently failed."""
```

```python
@dataclass
class RetryJob:
    session_id: UUID
    reason: str
    retry_count: int
    enqueued_at: datetime
    eligible_at: datetime  # enqueued_at + delay
```

#### 5.5 Exceptions

```python
# src/db/exceptions.py — additions

class InvalidTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""

class SessionFailedError(Exception):
    """Raised when a session enters the failed state."""
```

#### 5.6 SQL DDL

```sql
-- Migration: add failure tracking columns to sessions
ALTER TABLE sessions ADD COLUMN failure_reason VARCHAR(500);
ALTER TABLE sessions ADD COLUMN failure_stage VARCHAR(50);
ALTER TABLE sessions ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN last_retry_at TIMESTAMPTZ;
```

### 6. Implementation Notes

**Centralisation:**
- ALL status changes MUST go through `SessionStateMachine.transition()`
- Direct `session.status = X` assignments are forbidden outside the state machine
- The existing `SessionRepository.update_status()` is deprecated and replaced

**Atomicity:**
- Transition + audit event + flush happen in one transaction
- If flush fails, the transition is rolled back

**Retry Queue Implementation:**
- Uses Valkey (Redis-compatible) sorted set with score = eligible_at timestamp
- Worker polls `ZRANGEBYSCORE` for eligible jobs
- Exponential backoff: `delay = RETRY_DELAY_SECONDS * 2^retry_count`
- Max 3 retries; after that, permanently failed

**Concurrent Transitions (T23.5):**
- Use `SELECT ... FOR UPDATE` on the session row before transition
- Only one transaction can hold the lock; second attempt gets serialization error
- Retry the transition logic on serialization failure (optimistic concurrency)

**Failure Propagation:**
- When any stage fails, it must call `SessionStateMachine.transition(session, FAILED, reason=error_message)`
- The `failure_stage` records which stage failed (e.g., "asr_worker", "hallucination_detection")
- `notes_ready` is never set to True for failed sessions

### 7. Test Specification

| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T23.1 | U | Every valid and invalid transition pair from the exhaustive matrix | `validate_transition()` called for each pair | Valid transitions return True; invalid transitions raise `InvalidTransitionError`; all 9 valid + all invalid pairs tested |
| T23.2 | I | Session in `processing` state; a downstream stage raises an exception | `transition(session, FAILED, reason=error)` called | `session.status == FAILED`; `session.failure_reason` contains error message; `session.failure_stage` identifies the failing stage; `session.notes_ready == False` |
| T23.3 | I | Session in `failed` state with `retry_count < 3` | `RetryQueue.enqueue(session_id)` called | Session appears in Valkey sorted set; `dequeue()` returns it after delay expires |
| T23.4 | I | Session in `failed` state with existing transcript in `utterances` | `transition(session, PROCESSING)` called (retry) | Transcript is re-read from DB (not re-captured from audio); reprocessing proceeds; `retry_count` incremented |
| T23.5 | I | Two concurrent transactions attempt `transition(session, RECORDING)` simultaneously | Both attempt `SELECT ... FOR UPDATE` | One wins; the other gets serialization error and retries; final state is consistent |

### 8. Observability

| Signal | Type | Description |
|--------|------|-------------|
| `session.transition.total` | Counter | All transitions, tagged by (from, to) |
| `session.transition.rejected` | Counter | Invalid transition attempts |
| `session.failed.total` | Counter | Sessions entering failed state |
| `session.failed.by_stage` | Counter | Failures tagged by `failure_stage` |
| `session.retry.enqueued` | Counter | Sessions added to retry queue |
| `session.retry.completed` | Counter | Sessions successfully retried |
| `session.retry.permanent` | Counter | Sessions permanently failed after max retries |
| Span: `session.transition` | Trace span | Per-transition audit |

### 9. Rollback

- **Feature flag:** None (state machine is structural; cannot be disabled)
- **Database:** Revert migration to drop `failure_reason`, `failure_stage`, `retry_count`, `last_retry_at`
- **Code:** Restore ad-hoc `session.status = X` assignments in workers; remove `src/core/state_machine.py` and `src/workers/retry_queue.py`
- **Impact:** Loss of failure tracking and retry capability; transitions become unguarded again

### 10. Exit Checklist

- [ ] Every illegal transition is rejected with `InvalidTransitionError`
- [ ] Stage failure sets `failed`, never `complete` (NFR-R5)
- [ ] Failed sessions appear in retry queue
- [ ] Retrying a failed session reprocesses from retained transcript (NFR-R4)
- [ ] Concurrent transitions resolve to one winner (no split state)
- [ ] All tests T23.1–T23.5 pass
- [ ] Observability signals emitted

---

## S24 — Transcript Read API & Client View

### 1. Stage Identity

| Field | Value |
|-------|-------|
| **ID** | S24 |
| **Name** | Transcript Read API & Client View |
| **Block** | B3 — Transcript Integrity |
| **Owner** | Backend + Frontend |
| **Estimate** | 3 days |
| **Deps** | S22, S23 |
| **SRS** | FR-2.3, FR-7.8 precursor |

### 2. Context

This is the first user-visible deliverable. Users can now read and audio-scrub their own lecture transcripts. The paginated API serves transcript data filtered by session/subject with relevance and hallucination flags exposed. The client view uses wavesurfer.js for audio scrubbing synced to word-level timestamps.

This validates timestamp quality by eye — if words don't line up with audio, users will notice immediately.

### 3. Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| S22 | Upstream stage | Provides `is_relevant` and `filter_reason` flags to expose |
| S23 | Upstream stage | Provides session status and failure information |
| S12 | RLS policies | Transcript API must respect row-level security |
| wavesurfer.js | Frontend lib | Audio scrubbing component |
| MinIO | Object store | Audio files for playback |

### 4. Requirements Traced

| SRS ID | Requirement | How S24 implements |
|--------|-------------|---------------------|
| FR-2.3 | Transcript accessible to user | Paginated transcript API with RLS |
| FR-7.8 precursor | Audio-synced transcript view | wavesurfer.js playback synced to word timestamps |

### 5. Interface Contracts

#### 5.1 API Endpoints

```
GET /api/v1/sessions/{session_id}/transcript
```

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `offset` | int | 0 | Pagination offset (0-indexed utterance index) |
| `limit` | int | 50 | Page size (max 200) |
| `include_filtered` | bool | false | Include hallucination-flagged utterances |
| `speaker_tag` | str | null | Filter by speaker tag |
| `search` | str | null | Full-text search within transcript |

**Response 200:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "subject_id": "660e8400-e29b-41d4-a716-446655440001",
  "total_utterances": 342,
  "filtered_count": 12,
  "offset": 0,
  "limit": 50,
  "utterances": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440002",
      "seq": 0,
      "start_ms": 0,
      "end_ms": 4520,
      "text": "Welcome to today's lecture on machine learning.",
      "asr_confidence": 0.94,
      "asr_agreement": 0.87,
      "speaker_tag": "SPK_A",
      "is_relevant": true,
      "filter_reason": null,
      "word_timestamps": [
        {"word": "Welcome", "start_ms": 120, "end_ms": 380},
        {"word": "to", "start_ms": 380, "end_ms": 420},
        {"word": "today's", "start_ms": 420, "end_ms": 680},
        {"word": "lecture", "start_ms": 680, "end_ms": 960},
        {"word": "on", "start_ms": 960, "end_ms": 1020},
        {"word": "machine", "start_ms": 1020, "end_ms": 1380},
        {"word": "learning.", "start_ms": 1380, "end_ms": 1800}
      ]
    }
  ],
  "audio_url": "https://minio.example.com/lis-audio/session-abc/chunk-001.opus?presigned=...",
  "session_status": "complete",
  "notes_ready": false
}
```

**Response 403:** (RLS violation — session belongs to another user)
```json
{
  "detail": "Session not found"
}
```
(404, not 403 — does not leak existence)

#### 5.2 Pydantic Schemas

```python
# src/api/schemas/transcript.py

class WordTimestamp(BaseModel):
    word: str
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)

class TranscriptUtterance(BaseModel):
    id: UUID
    seq: int
    start_ms: int
    end_ms: int
    text: str
    asr_confidence: float | None
    asr_agreement: float | None
    speaker_tag: str | None
    is_relevant: bool | None
    filter_reason: str | None
    word_timestamps: list[WordTimestamp] = []

    model_config = ConfigDict(from_attributes=True)

class TranscriptResponse(BaseModel):
    session_id: UUID
    subject_id: UUID
    total_utterances: int
    filtered_count: int
    offset: int
    limit: int
    utterances: list[TranscriptUtterance]
    audio_url: str | None
    session_status: str
    notes_ready: bool
```

#### 5.3 Repository Methods

```python
# src/db/repositories/utterance_repo.py — additions

class UtteranceRepository:
    # ... existing methods ...

    async def get_transcript_page(
        self,
        subject_id: UUID,
        session_id: UUID,
        offset: int = 0,
        limit: int = 50,
        include_filtered: bool = False,
        speaker_tag: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Utterance], int]:
        """
        Get a paginated transcript page with optional filters.
        Returns (utterances, total_count).
        Respects RLS via SET LOCAL app.user_id.
        """

    async def count_filtered(self, subject_id: UUID, session_id: UUID) -> int:
        """Count utterances where is_relevant = false for a session."""
```

#### 5.4 SQL Queries

```sql
-- Paginated transcript with filters
SELECT u.*
FROM utterances u
JOIN sessions s ON u.session_id = s.id
WHERE u.subject_id = :subject_id
  AND u.session_id = :session_id
  AND (:include_filtered = true OR u.is_relevant IS DISTINCT FROM false)
  AND (:speaker_tag IS NULL OR u.speaker_tag = :speaker_tag)
  AND (:search IS NULL OR u.text ILIKE '%' || :search || '%')
ORDER BY u.seq
OFFSET :offset
LIMIT :limit;

-- Count for pagination
SELECT COUNT(*)
FROM utterances u
WHERE u.subject_id = :subject_id
  AND u.session_id = :session_id
  AND (:include_filtered = true OR u.is_relevant IS DISTINCT FROM false);

-- Count filtered (hallucination) utterances
SELECT COUNT(*)
FROM utterances
WHERE subject_id = :subject_id
  AND session_id = :session_id
  AND is_relevant = false;
```

#### 5.5 Client View

```
File: frontend/src/components/TranscriptView.tsx (or equivalent)
```

**Component Structure:**
```
TranscriptView
├── AudioPlayer (wavesurfer.js)
│   ├── WaveformDisplay
│   ├── PlaybackControls (play/pause/seek)
│   └── CurrentTimeDisplay
├── UtteranceList
│   ├── UtteranceItem (per utterance)
│   │   ├── TimestampBadge (start_ms → mm:ss)
│   │   ├── SpeakerTag (SPK_A / SPK_B)
│   │   ├── TextContent
│   │   ├── ConfidenceBadge (asr_confidence)
│   │   └── AgreementBadge (asr_agreement)
│   └── FilteredUtteranceItem (dimmed, expandable)
├── TranscriptControls
│   ├── FilterToggle (include/exclude filtered)
│   ├── SpeakerFilter
│   └── SearchBox
└── PaginationControls
```

**Audio Sync Behavior:**
- Clicking an utterance seeks audio to `start_ms`
- Playing audio highlights the current utterance based on `start_ms <= current_time < end_ms`
- Word-level timestamps enable sub-utterance highlighting (future enhancement)
- Playback position synced within 500ms accuracy (T24.3)

**wavesurfer.js Integration:**
```typescript
// Pseudocode for audio-synced transcript
const wavesurfer = WaveSurfer.create({
  container: '#waveform',
  url: audioUrl,
  plugins: [TimelinePlugin, RegionsPlugin],
});

// Sync playback position to transcript
wavesurfer.on('timeupdate', (currentTimeMs: number) => {
  const activeUtterance = utterances.find(
    u => u.start_ms <= currentTimeMs && u.start_ms < u.end_ms
  );
  setActiveUtterance(activeUtterance?.id ?? null);
});

// Click utterance to seek
const handleUtteranceClick = (utterance: TranscriptUtterance) => {
  wavesurfer.seekTo(utterance.start_ms / wavesurfer.getDuration());
};
```

### 6. Implementation Notes

**RLS Enforcement:**
- Transcript API uses the same `get_db_session()` dependency that sets `app.user_id`
- RLS policies on `utterances` and `sessions` automatically filter results
- No manual user_id check needed; PostgreSQL handles isolation

**Word Timestamps:**
- S19 produces word-level timestamps via wav2vec2 forced alignment
- Stored as a JSONB column or separate table (TBD at S19 implementation)
- For S24, assume word timestamps are available; if not, utterance-level timestamps suffice

**Audio URL:**
- Presigned URL from MinIO (S14 storage client)
- Expires after 1 hour; client must request fresh URL
- URL scoped to the specific session's audio

**Performance:**
- Pagination ensures O(limit) query time regardless of total utterances
- Index on `(subject_id, session_id, seq)` supports efficient pagination
- Full-text search uses PostgreSQL `ILIKE` (acceptable for MVP; upgrade to `tsvector` later)

**Hallucination Flags:**
- By default, filtered utterances are excluded (`include_filtered=false`)
- User can toggle to include them (shown dimmed with red badge)
- `filtered_count` in response tells user how many are hidden

### 7. Test Specification

| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T24.1 | I | Session with 200 utterances; pages of size 50 | Request pages 0, 1, 2, 3 in sequence | Each page returns exactly 50 utterances (last page may be less); `total_utterances == 200`; no duplicate utterances across pages; `offset` values are correct |
| T24.2 | I | User A's session; User B requests it via API | GET `/sessions/{id}/transcript` | Response is 404 (not 403); no data leaked; RLS blocks cross-user access |
| T24.3 | E | Session with audio and aligned transcript | Click an utterance in the client view | Audio seeks to `start_ms` position; playback begins within 500ms of click; current utterance is highlighted |
| T24.4 | M | 3 real lecture sessions with known content | Human reviewer reads transcript while listening to audio | Reviewer confirms: (a) transcript is readable, (b) timestamps align with audio within 1s, (c) hallucination flags are reasonable |
| T24.5 | P | 60-minute session with ~600 utterances | Load transcript page (first 50 utterances) | Page loads in < 1s (server + client render) |

### 8. Observability

| Signal | Type | Description |
|--------|------|-------------|
| `transcript.api.request` | Counter | API requests, tagged by session_id and include_filtered |
| `transcript.api.latency` | Histogram | API response time |
| `transcript.api.pagination` | Histogram | Page sizes requested |
| `transcript.api.rls_block` | Counter | RLS-blocked requests (404 responses) |
| `transcript.client.load_time` | Histogram | Client-side page load time (if instrumented) |
| Span: `transcript.get_page` | Trace span | Server-side transcript page fetch |

### 9. Rollback

- **Feature flag:** Remove transcript routes from the FastAPI app; hide transcript tab in client
- **Database:** No migration to revert
- **Code:** Remove `src/api/routes/transcript.py`, `src/api/schemas/transcript.py`, `frontend/src/components/TranscriptView.tsx`
- **Impact:** No user-visible transcript; data remains in DB for other uses

### 10. Exit Checklist

- [ ] Paginated API returns correct pages with stable ordering
- [ ] RLS blocks cross-user access (404 response)
- [ ] Clicking an utterance plays correct audio position within 500ms
- [ ] Human review confirms transcript readability and timestamp alignment
- [ ] Transcript page loads in < 1s for 60-minute session
- [ ] All tests T24.1–T24.5 pass
- [ ] Observability signals emitted
- [ ] **Phase 1 of the SRS is complete and independently useful**

---

## Cross-Stage Contracts

### Worker Orchestration Order

```
S19 (ASR) → S20 (Diarisation) → S21 (Dual ASR) → S22 (Hallucination) → S24 (API ready)
                                ↘ S23 (State Machine) ←── governs all transitions
```

### State Transitions Through Block 3

```
created → recording → transcribed → processing → complete
                                    ↓
                                 failed → (retry) → processing → complete
```

### Data Flow

```
Audio chunks (MinIO)
    ↓ S17 (Preprocess)
VAD regions + clean audio
    ↓ S19 (Primary ASR)
Utterances (text, timestamps, confidence, speaker_tag)
    ↓ S21 (Dual ASR)
Utterances + asr_agreement
    ↓ S22 (Hallucination Detection)
Utterances + is_relevant + filter_reason
    ↓ S24 (API)
TranscriptResponse (paginated, filtered, audio-synced)
```

### Column Usage Summary

| Column | Set by | Read by | Values |
|--------|--------|---------|--------|
| `asr_agreement` | S21 | S22, S24 | NULL (no secondary), 0.0–1.0 |
| `is_relevant` | S22 (or A1 agent later) | S24 | NULL (unfiltered), true, false |
| `filter_reason` | S22 | S24 | NULL, `asr_hallucination`, `asr_hallucination_*` |
| `outlier_score` | S22 | S24 | NULL, composite score |
| `failure_reason` | S23 | S24 | NULL, error message string |
| `failure_stage` | S23 | S24 | NULL, stage identifier string |
| `retry_count` | S23 | Internal | 0 (default), incremented on retry |

---

## Appendix A — Full Migration Plan

```sql
-- Migration: S23 — Session failure tracking columns
-- Depends: 8b67f8790b48 (S12 RLS)

-- Add failure tracking columns to sessions
ALTER TABLE sessions ADD COLUMN failure_reason VARCHAR(500);
ALTER TABLE sessions ADD COLUMN failure_stage VARCHAR(50);
ALTER TABLE sessions ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN last_retry_at TIMESTAMPTZ;

-- Verify check constraint still holds (status enum unchanged)
-- The existing ck_session_status constraint already covers all enum values
```

**Downgrade:**
```sql
ALTER TABLE sessions DROP COLUMN IF EXISTS failure_reason;
ALTER TABLE sessions DROP COLUMN IF EXISTS failure_stage;
ALTER TABLE sessions DROP COLUMN IF EXISTS retry_count;
ALTER TABLE sessions DROP COLUMN IF EXISTS last_retry_at;
```

**No migration needed for S21 or S22** — they use existing columns.

---

## Appendix B — Config Keys Added

```yaml
# config/models.yaml — S21 additions
secondary_asr_model: "nvidia/canary-25b-12b-pt"
secondary_asr_engine: "faster_whisper"
secondary_asr_compute_type: "int8_float16"
secondary_asr_device: "cuda"
secondary_asr_beam_size: 5
```

```python
# src/core/config.py — all Block 3 additions

# S21 — Dual ASR
SECONDARY_ASR_MODEL: str = "nvidia/canary-25b-12b-pt"
SECONDARY_ASR_ENGINE: str = "faster_whisper"
SECONDARY_ASR_COMPUTE_TYPE: str = "int8_float16"
SECONDARY_ASR_BEAM_SIZE: int = 5
DUAL_ASR_ENABLED: bool = True
AGREEMENT_THRESHOLD: float = 0.5

# S22 — Hallucination Detection
HALLUCINATION_DETECTION_ENABLED: bool = True
HALLUCINATION_AGREEMENT_THRESHOLD: float = 0.5
HALLUCINATION_MAX_REPEAT_NGRAM: int = 3
HALLUCINATION_MAX_REPEAT_COUNT: int = 3
HALLUCINATION_VAD_MARGIN_MS: int = 200
HALLUCINATION_MIN_UTTERANCE_LENGTH_MS: int = 500

# S23 — Retry Queue
RETRY_MAX_ATTEMPTS: int = 3
RETRY_DELAY_SECONDS: int = 60
RETRY_BACKOFF_MULTIPLIER: float = 2.0
```

---

## Appendix C — Observability Dashboard

**Grafana Panels (Block 3):**

| Panel | Query | Type |
|-------|-------|------|
| Dual ASR Duration | `histogram_quantile(0.95, dual_asr_session_duration_ms)` | Time series |
| Agreement Distribution | `histogram_quantile buckets of dual_asr_utterance_agreement` | Histogram |
| Hallucination Rate | `hallucination_total_flagged / total_utterances` | Gauge |
| Hallucination by Detector | `hallucination_detector_{cross_model,repetition,vad}` | Stacked bar |
| Session State Distribution | `session_transition_total by (to_status)` | Pie chart |
| Failed Sessions | `session_failed_total by (failure_stage)` | Counter |
| Retry Queue Depth | `session_retry_enqueued - session_retry_completed` | Gauge |
| Transcript API Latency | `histogram_quantile(0.99, transcript_api_latency)` | Time series |
| Transcript Page Size | `histogram_quantile(50, transcript_api_pagination)` | Histogram |

**Trace Spans (Block 3):**

| Span Name | Parent | Attributes |
|-----------|--------|------------|
| `dual_asr.process_session` | Worker span | `session_id`, `utterances_count`, `mean_agreement` |
| `hallucination.detect_session` | Worker span | `session_id`, `flagged_count`, `detectors_fired` |
| `session.transition` | Any span | `from_status`, `to_status`, `session_id`, `reason` |
| `transcript.get_page` | API span | `session_id`, `offset`, `limit`, `total_utterances` |

---

*Document version: 1.0*
*Created: 2026-09-12*
*Block 3 spec — grounded in codebase state at S20 gate*

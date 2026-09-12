# S21 — Dual-ASR Ensemble
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Run the second-place S06 model (Canary-Qwen 2.5B) alongside the primary ASR model on every session, align outputs by timestamp, and compute a per-utterance agreement score that signals transcription reliability.

**Component Boundaries:**
- **Allowed:** `src/workers/asr_ensemble.py`, `src/services/asr/`, `config/models.yaml` (secondary model entry), `tests/test_dual_asr.py`
- **Off-limits:** Primary ASR worker (S19) internals, hallucination detectors (S22), embedding (S25)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| faster-whisper | 1.0.x | Primary ASR inference (CTranslate2 backend) |
| nvidia/canary-2.5b | 2.5B | Secondary ASR model |
| bitsandbytes | 0.43.x | 8-bit quantization for Canary |
| torch | 2.x | Canary inference runtime |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Ensemble Processing Flow:**
```
audio chunk
  ├─ Primary ASR (whisper-large-v3-turbo) → utterances[]
  └─ Secondary ASR (canary-qwen-2.5b) → utterances[]
       │
       ▼
  Timestamp alignment (IOWers or Hungarian)
       │
       ▼
  Per-utterance agreement computation
       │
       ▼
  Write asr_agreement to DB
```

**Agreement Score Definition:**
```
agreement(text_primary, text_secondary) = 1.0 - WER(text_primary, text_secondary)
```
- Range: [0.0, 1.0] where 1.0 = identical output
- If secondary fails entirely: agreement = NULL (not 0.0)

**Pydantic Models:**
```python
# src/services/asr/ensemble.py
from pydantic import BaseModel, Field
from uuid import UUID
from enum import Enum

class ASRModel(BaseModel):
    name: str
    model_id: str
    compute_type: str
    device: str = "cuda"

class EnsembleConfig(BaseModel):
    primary: ASRModel
    secondary: ASRModel
    alignment_method: str = "iower"  # iower | hungarian
    agreement_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    secondary_timeout_s: int = 120

class UtteranceAlignment(BaseModel):
    primary_utt_id: UUID
    secondary_utt_id: UUID | None  # None if secondary produced no match
    primary_text: str
    secondary_text: str | None
    agreement: float | None
    start_ms: int
    end_ms: int

class EnsembleResult(BaseModel):
    primary_utterances: list[dict]
    secondary_utterances: list[dict]
    alignments: list[UtteranceAlignment]
    secondary_failed: bool
    total_utterances: int
    mean_agreement: float | None
```

**config/models.yaml additions:**
```yaml
# Secondary ASR (S21)
asr_secondary_model: "nvidia/canary-2.5b"
asr_secondary_compute_type: "int8"
asr_secondary_device: "cuda"
asr_secondary_quantization: "bitsandbytes-4bit"
asr_secondary_timeout_s: 120
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Add Canary-Qwen 2.5B config to `config/models.yaml` | Config loads, model available |
| 2 | Implement `SecondaryASRWorker` with same interface as primary | Worker starts, health check passes |
| 3 | Implement `EnsembleRunner` that runs both models in parallel | Both models produce utterances for test audio |
| 4 | Implement timestamp alignment algorithm (IOWers / edit-distance on timestamps) | Aligned pairs match correctly |
| 5 | Compute per-utterance agreement score | Agreement scores in valid range |
| 6 | Persist `asr_agreement` to `utterances` table | Column updated in DB |
| 7 | Add graceful fallback: secondary failure → proceed with primary alone | Pipeline continues on secondary failure |
| 8 | Run integration tests | All T21.x pass |

**Atomic Sub-tasks:**
1. Secondary model config and loading
2. Parallel ASR runner (asyncio.gather with timeout)
3. Timestamp alignment algorithm
4. Agreement score computation
5. DB persistence of agreement scores
6. Secondary-failure fallback handling

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Secondary model fails to load | Log warning, proceed with primary only, agreement=NULL |
| Secondary inference timeout | Kill secondary task, proceed with primary, agreement=NULL |
| Zero utterances from secondary | Agreement=NULL for all utterances (cannot compute) |
| Timestamp overlap > 50% | Use primary timestamps as canonical |
| Different utterance counts | Align greedily by overlap, leave unmatched as NULL |
| Secondary OOM | Catch CUDA OOM, log, proceed with primary alone |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Runner pattern: `EnsembleRunner` orchestrates both workers
- Timeout pattern: `asyncio.wait_for()` with configurable timeout
- Fallback pattern: secondary failure never blocks primary

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`asr_ensemble.py`, `secondary_asr_worker.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Repository Interface:**
```python
# src/services/asr/ensemble.py
class EnsembleRunner:
    async def run_ensemble(
        self,
        audio_path: str,
        session_id: UUID,
        subject_id: UUID,
    ) -> EnsembleResult:
        """Run both ASR models and compute agreement."""

    def compute_agreement(self, primary_text: str, secondary_text: str) -> float:
        """Compute agreement score between two transcriptions."""
```

**DB Update:**
```sql
UPDATE utterances
SET asr_agreement = $1
WHERE subject_id = $2 AND session_id = $3 AND seq = $4;
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `ASR_SECONDARY_MODEL` | string | Secondary model ID | `nvidia/canary-2.5b` |
| `ASR_SECONDARY_COMPUTE_TYPE` | string | Quantization | `int8` |
| `ASR_SECONDARY_TIMEOUT_S` | int | Inference timeout | `120` |
| `ASR_SECONDARY_ENABLED` | bool | Enable/disable dual ASR | `true` |

**Third-Party Integration Contracts:**
- faster-whisper: primary model inference (same as S19)
- bitsandbytes: 8-bit quantization for Canary-Qwen

**Version Pins:**
- nvidia/canary-2.5b model version frozen in config
- bitsandbytes >= 0.43.x for int8 quantization

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T21.1 | I | `pytest tests/test_dual_asr.py::test_both_models_run -v` | Both models run; agreement score computed for every utterance |
| T21.2 | V | `pytest tests/test_dual_asr.py::test_agreement_correlates_with_wer -v` | Agreement correlates negatively with word error on S05 labelled set |
| T21.3 | I | `pytest tests/test_dual_asr.py::test_secondary_failure_fallback -v` | If secondary fails, pipeline proceeds on primary alone with agreement NULL |
| T21.4 | P | `pytest tests/test_dual_asr.py::test_dual_asr_nfr_p3 -v` | Dual ASR completes within NFR-P3 post-session budget |

**Test Case Details (Given/When/Then):**

**T21.1 — Both models run; agreement score computed for every utterance**
- **Given:** a 5-minute audio file with 30+ utterances
- **When:** `EnsembleRunner.run_ensemble()` is called
- **Then:** both primary and secondary produce utterances; every primary utterance has a non-NULL `asr_agreement` score in [0.0, 1.0]

**T21.2 — Agreement correlates negatively with word error**
- **Given:** 30 audio clips with S05 ground-truth labels
- **When:** dual ASR is run on each clip; WER is computed against ground truth
- **Then:** Pearson correlation between agreement scores and WER is < -0.3 (agreement is informative)

**T21.3 — Secondary failure falls back to primary**
- **Given:** secondary model endpoint is unreachable (mock failure)
- **When:** `EnsembleRunner.run_ensemble()` is called
- **Then:** primary utterances are produced; all `asr_agreement` values are NULL; no exception raised

**T21.4 — Dual ASR within NFR-P3 budget**
- **Given:** a 60-minute lecture recording
- **When:** dual ASR is run
- **Then:** total wall-clock time is within NFR-P3 post-session budget (2x real-time)

**Verification Commands:**
```bash
uv run pytest tests/test_dual_asr.py -v && \
uv run mypy --strict src/services/asr/ && \
uv run ruff check src/services/asr/
```

**Exit Criteria:**
- [ ] T21.1 passes — both models run; agreement computed for every utterance
- [ ] T21.2 passes — agreement correlates negatively with word error
- [ ] T21.3 passes — secondary failure gracefully handled
- [ ] T21.4 passes — within NFR-P3 budget

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Canary-Qwen 2.5B requires bitsandbytes 8-bit quantization to fit in 4GB VRAM alongside primary model — if quantization not configured, OOM occurs
- Timestamp alignment between two models with different segment boundaries is non-trivial — naive index-matching produces misaligned pairs
- Secondary model may emit different language/script for same audio — use WER-based agreement, not exact match

**Fallback Instructions:**
- If secondary model OOM: reduce `asr_secondary_quantization` or disable dual ASR via `ASR_SECONDARY_ENABLED=false`
- If alignment algorithm fails: fall back to primary-only with NULL agreement
- If secondary timeout: log, proceed with primary, alert if > 10% of sessions affected

**Rollback Procedure:**
- Set `ASR_SECONDARY_ENABLED=false` in env — disables dual ASR without code changes
- No database migration rollback needed (column `asr_agreement` is nullable)

---

### 9. Observability (if applicable)

**Metrics Added:**
- `asr_ensemble_total`: counter of ensemble runs (labels: status=success/secondary_failed/both_failed)
- `asr_agreement_score`: histogram of agreement scores across utterances
- `asr_ensemble_latency_seconds`: histogram of total ensemble wall-clock time
- `asr_secondary_inference_seconds`: histogram of secondary model inference time

**Tracing/Logging:**
- Span: `asr.ensemble.run` with attributes (session_id, primary_utt_count, secondary_utt_count, mean_agreement)
- Log: WARN on secondary model failure with reason
- Log: INFO on ensemble completion with agreement summary

**Alerts:**
- Secondary model failure rate > 10% in 1 hour: configuration or hardware issue
- Mean agreement score < 0.3 across sessions: models may be misconfigured
- Secondary inference time > 2x primary: investigate model performance

---

### 10. Exit Checklist

- [ ] All tests pass (T21.1, T21.2, T21.3, T21.4)
- [ ] `asr_agreement` column populated for all utterances in dual-ASR mode
- [ ] Secondary failure handled gracefully without blocking pipeline
- [ ] Dual ASR within NFR-P3 performance budget
- [ ] Canary-Qwen 2.5B loads successfully with 8-bit quantization

# S22 — Hallucination Detection
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement three independent hallucination detectors — cross-model disagreement, repetition detection, and VAD contradiction — that flag spurious ASR output without removing it, making the canonical Whisper hallucination failure modes caught and auditable.

**Component Boundaries:**
- **Allowed:** `src/services/hallucination/`, `src/workers/hallucination_detector.py`, `tests/test_hallucination.py`
- **Off-limits:** Primary/secondary ASR workers (S19, S21), A1 relevance filter (S41)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Silero VAD | 4.x | Speech activity detection for VAD contradiction |
| pytest | 8.x | Integration tests |
| numpy | 1.26.x | N-gram repetition computation |

---

### 2. State Machine & Domain Schemas

**Detection Pipeline:**
```
utterance (with asr_agreement, text, start_ms, end_ms)
  │
  ├─ Detector A: Cross-Model Disagreement
  │   └─ if agreement=NULL AND secondary_text has content → potential hallucination
  │
  ├─ Detector B: Repetition Detector
  │   └─ n-gram loop detection (Whisper degeneration pattern)
  │
  └─ Detector C: VAD Contradiction
      └─ text present in region VAD marked speechless
  │
  ▼
  Any detector triggers → mark is_relevant=false, filter_reason='asr_hallucination'
  (soft delete, never removed from DB)
```

**Hallucination Types:**
| Type | Signal | Example |
|------|--------|---------|
| Cross-model disagreement | Secondary emits text where primary emits silence (or vice versa) | Whisper generates "Thank you for watching" in silence |
| Repetition degeneration | Same 3-gram repeated 3+ times consecutively | "I think that that that that that" |
| VAD contradiction | Non-empty transcript text in VAD-speechless region | Text generated from room noise |

**Pydantic Models:**
```python
# src/services/hallucination/models.py
from pydantic import BaseModel, Field
from enum import Enum
from uuid import UUID


class HallucinationType(str, Enum):
    CROSS_MODEL_DISAGREEMENT = "cross_model_disagreement"
    REPETITION_DEGENERATION = "repetition_degeneration"
    VAD_CONTRADICTION = "vad_contradiction"


class HallucinationFlag(BaseModel):
    utterance_id: UUID
    hallucination_type: HallucinationType
    confidence: float = Field(..., ge=0.0, le=1.0)
    detail: str  # human-readable explanation


class DetectionResult(BaseModel):
    utterance_id: UUID
    is_hallucination: bool
    flags: list[HallucinationFlag]
    action: str  # "flag" | "pass"
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Implement cross-model disagreement detector | Detector correctly flags utterances with disagreement |
| 2 | Implement repetition detector (n-gram loop detection) | Catches deliberately repeated phrases |
| 3 | Implement VAD contradiction detector | Flags text in VAD-speechless regions |
| 4 | Build `HallucinationDetector` orchestrating all three | All detectors run in sequence |
| 5 | Implement flagging logic: mark `is_relevant=false, filter_reason='asr_hallucination'` | DB records flagged correctly |
| 6 | Add hallucination metrics tracking | Rate tracked on S04 corpus |
| 7 | Run evaluation on S05 labelled set | T22.x pass |

**Atomic Sub-tasks:**
1. Cross-model disagreement detector
2. Repetition detector (n-gram analysis)
3. VAD contradiction detector
4. Hallucination flagging orchestrator
5. Metrics tracking for hallucination rates
6. Evaluation against S04 corpus and S05 ground truth

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| All three detectors flag same utterance | Deduplicate flags; store all types in filter_reason |
| VAD data unavailable | Skip VAD contradiction detector; log warning |
| Secondary ASR unavailable (NULL agreement) | Skip cross-model detector; rely on repetition + VAD |
| False positive on legitimate repetition (e.g., "the the theory") | Tune n-gram threshold; allow 2-gram repeats, flag 3+ |
| Empty utterance text | Skip all detectors for that utterance |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: each detector is an independent strategy class
- Pipeline pattern: detectors run in sequence, first flag wins
- Soft-delete pattern: flagged utterances marked, never removed

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`cross_model_detector.py`, `repetition_detector.py`, `vad_contradiction_detector.py`)
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
# src/services/hallucination/detector.py
class HallucinationDetector:
    async def detect(
        self,
        utterance_id: UUID,
        text: str,
        start_ms: int,
        end_ms: int,
        asr_agreement: float | None,
        secondary_text: str | None,
        vad_segments: list[tuple[int, int]] | None,  # [(start_ms, end_ms), ...]
    ) -> DetectionResult:
        """Run all three detectors and return combined result."""

    async def flag_utterance(
        self,
        subject_id: UUID,
        utterance_id: UUID,
        flags: list[HallucinationFlag],
    ) -> None:
        """Mark utterance as hallucination in DB."""
```

**DB Update (Soft Delete):**
```sql
UPDATE utterances
SET is_relevant = false,
    filter_reason = 'asr_hallucination'
WHERE subject_id = $1 AND id = $2;
```

**Repetition Detector Algorithm:**
```python
def detect_repetition(text: str, min_ngram: int = 3, min_repeat: int = 3) -> bool:
    """
    Detect Whisper-style repetition degeneration.
    Checks for n-gram loops of length >= min_ngram repeated >= min_repeat times.
    """
    words = text.lower().split()
    for n in range(min_ngram, min(len(words) // min_repeat + 1, 8)):
        for i in range(len(words) - n * min_repeat + 1):
            ngram = tuple(words[i : i + n])
            count = 0
            for j in range(i, len(words) - n + 1, n):
                if tuple(words[j : j + n]) == ngram:
                    count += 1
                else:
                    break
            if count >= min_repeat:
                return True
    return False
```

**VAD Contradiction Algorithm:**
```python
def detect_vad_contradiction(
    text: str,
    start_ms: int,
    end_ms: int,
    vad_segments: list[tuple[int, int]],
    min_speech_ratio: float = 0.3,
) -> bool:
    """
    If >70% of the utterance duration falls in VAD-speechless regions,
    flag as VAD contradiction.
    """
    utterance_duration = end_ms - start_ms
    speech_duration = sum(
        min(end_ms, seg_end) - max(start_ms, seg_start)
        for seg_start, seg_end in vad_segments
        if min(end_ms, seg_end) > max(start_ms, seg_start)
    )
    speech_ratio = speech_duration / utterance_duration if utterance_duration > 0 else 0
    return speech_ratio < (1 - min_speech_ratio)  # mostly silence
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `HALLUCINATION_DETECTION_ENABLED` | bool | Enable/disable detection | `true` |
| `REPETITION_MIN_NGRAM` | int | Minimum n-gram size for repetition | `3` |
| `REPETITION_MIN_REPEAT` | int | Minimum consecutive repeats | `3` |
| `VAD_CONTRADICTION_THRESHOLD` | float | Speech ratio below which to flag | `0.3` |
| `HALLUCINATION_RATE_ALERT_THRESHOLD` | float | Alert if rate exceeds this | `0.05` |

**Third-Party Integration Contracts:**
- Silero VAD: speech activity detection from S17 preprocessing
- WER computation: used in cross-model disagreement and evaluation

**Version Pins:**
- Silero VAD model pinned in requirements
- numpy >= 1.26.x for n-gram operations

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T22.1 | V | `pytest tests/test_hallucination.py::test_silence_produces_zero_retained -v` | A 60s silence injected into real audio produces zero retained utterances |
| T22.2 | V | `pytest tests/test_hallucination.py::test_repetition_detector_catches_loops -v` | A deliberately repeated-phrase sample is caught by the repetition detector |
| T22.3 | V | `pytest tests/test_hallucination.py::test_false_positive_rate -v` | Detectors' false-positive rate on real speech < 2% |
| T22.4 | I | `pytest tests/test_hallucination.py::test_flagged_not_deleted -v` | Flagged utterances are marked, not deleted |
| T22.5 | V | `pytest tests/test_hallucination.py::test_hallucination_rate_tracked -v` | Measured hallucination rate on S04 corpus recorded as a tracked metric |

**Test Case Details (Given/When/Then):**

**T22.1 — Silence produces zero retained utterances**
- **Given:** a 60-second audio clip of pure silence is preprocessed and transcribed
- **When:** hallucination detection runs on the resulting utterances
- **Then:** all utterances are flagged as hallucinations; zero utterances remain with `is_relevant=true`

**T22.2 — Repetition detector catches loops**
- **Given:** an utterance with text "I think that that that that that that is correct"
- **When:** the repetition detector runs
- **Then:** the utterance is flagged with `hallucination_type=repetition_degeneration`

**T22.3 — False-positive rate < 2% on real speech**
- **Given:** 50 utterances of real, verified lecture speech (S05 ground truth)
- **When:** all three detectors run on these utterances
- **Then:** fewer than 1 utterance (2%) is incorrectly flagged

**T22.4 — Flagged utterances marked, not deleted**
- **Given:** an utterance is flagged as a hallucination
- **When:** the database is queried for that utterance
- **Then:** the row still exists; `is_relevant=false` and `filter_reason='asr_hallucination'`

**T22.5 — Hallucination rate tracked on S04 corpus**
- **Given:** the S04 audio corpus with known characteristics
- **When:** hallucination detection is run across the corpus
- **Then:** the hallucination rate (flagged / total utterances) is recorded as a metric and matches expected range (< 5%)

**Verification Commands:**
```bash
uv run pytest tests/test_hallucination.py -v && \
uv run mypy --strict src/services/hallucination/ && \
uv run ruff check src/services/hallucination/
```

**Exit Criteria:**
- [ ] T22.1 passes — silence produces zero retained utterances
- [ ] T22.2 passes — repetition detector catches loops
- [ ] T22.3 passes — false-positive rate < 2%
- [ ] T22.4 passes — flagged utterances marked, not deleted
- [ ] T22.5 passes — hallucination rate tracked as metric

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Whisper degeneration produces "Thank you for watching" in silence — this is the canonical hallucination the cross-model detector must catch
- Legitimate repeated phrases (e.g., "the the theory") can trigger false positives — tune n-gram threshold carefully
- VAD from S17 may not be available for all sessions — detectors must handle missing VAD data gracefully
- Repetition detector on short utterances (< 10 words) is unreliable — skip or reduce threshold

**Fallback Instructions:**
- If VAD data unavailable: skip VAD contradiction detector, rely on other two
- If false-positive rate > 2%: increase `REPETITION_MIN_REPEAT` or `VAD_CONTRADICTION_THRESHOLD`
- If hallucination rate > 5% on production: investigate ASR model quality, not detector tuning

**Rollback Procedure:**
- Set `HALLUCINATION_DETECTION_ENABLED=false` — no utterances flagged
- Existing flagged utterances remain flagged (safe state)
- No database migration rollback needed

---

### 9. Observability (if applicable)

**Metrics Added:**
- `hallucination_detection_total`: counter of utterances processed (labels: result=clean/flagged)
- `hallucination_rate`: gauge of flagged / total utterances per session
- `hallucination_type_total`: counter by type (labels: type=cross_model/repetition/vad_contradiction)
- `hallucination_detection_latency_seconds`: histogram of detection time per utterance

**Tracing/Logging:**
- Span: `hallucination.detect` with attributes (utterance_id, type, confidence)
- Log: WARN on each flagged utterance with reason
- Log: INFO on session hallucination summary

**Alerts:**
- Hallucination rate > 5% across 10 sessions: ASR model degradation
- VAD contradiction rate > 10%: VAD configuration issue
- False-positive complaints from users: investigate detector tuning

---

### 10. Exit Checklist

- [ ] All tests pass (T22.1, T22.2, T22.3, T22.4, T22.5)
- [ ] Three detectors implemented and operational
- [ ] Flagged utterances soft-deleted (`is_relevant=false`), not removed
- [ ] Hallucination rate tracked as metric
- [ ] False-positive rate < 2% on real speech
- [ ] Canonical Whisper hallucination failure mode caught

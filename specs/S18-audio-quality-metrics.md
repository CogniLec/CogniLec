# S18 — Audio Quality Metrics & Operator Warning
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Compute per-chunk audio quality metrics (SNR, VAD speech ratio, clipping rate), aggregate to a session quality score, and emit real-time warnings to the operator when quality falls below threshold.

**Component Boundaries:**
- **Allowed:** `src/services/audio_quality/`, `src/api/routes/session_stream.py`, `src/client/components/AudioWarning.tsx`, `tests/test_audio_quality.py`
- **Off-limits:** Preprocessing chain (S17), ASR (S19), chunk upload (S16)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| numpy | 1.26.x | Audio array computation |
| soundfile | 0.12.x | Audio I/O |
| SSE-Starlette | 1.x | Real-time warning delivery |
| FastAPI | 0.141.1 | API layer |

---

### 2. State Machine & Domain Schemas

**Quality Threshold States:**
```
NORMAL → DEGRADED → WARNING → CRITICAL
   ↑        ↑          ↑          ↑
   └────────┴──────────┴──────────┘
         (recover on improvement)
```

**Per-Chunk Metrics Schema:**
```python
# src/services/audio_quality/models.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class ChunkQualityMetrics(BaseModel):
    session_id: UUID
    sequence: int
    snr_db: float = Field(..., description="Signal-to-noise ratio in dB")
    speech_ratio: float = Field(..., ge=0.0, le=1.0, description="Fraction of chunk with speech")
    clipping_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Fraction of samples at max amplitude"
    )
    lufs: float | None = Field(None, description="Integrated loudness")
    rms_db: float | None = None
    computed_at: datetime


class SessionQualityScore(BaseModel):
    session_id: UUID
    avg_snr_db: float
    avg_speech_ratio: float
    avg_clipping_rate: float
    overall_score: float = Field(..., ge=0.0, le=1.0, description="0=worst, 1=best")
    chunk_count: int
    window_snr_db: float = Field(..., description="Rolling window SNR")
    status: str = "normal"  # normal, degraded, warning, critical
    last_updated: datetime


class QualityWarning(BaseModel):
    session_id: UUID
    warning_type: str  # "low_snr", "low_speech_ratio", "high_clipping"
    severity: str  # "degraded", "warning", "critical"
    message: str
    metric_value: float
    threshold: float
    timestamp: datetime
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Implement per-chunk SNR computation | SNR correct on fixtures of known SNR |
| 2 | Implement per-chunk speech ratio (from VAD) | Ratio matches VAD output |
| 3 | Implement per-chunk clipping rate | Clipping rate correct on clipped fixture |
| 4 | Implement session quality score aggregation | Score persisted on session completion |
| 5 | Implement rolling window threshold check | Sub-threshold triggers warning |
| 6 | Implement SSE warning event emission | Warning appears in client within 10s |
| 7 | Implement threshold configuration | Threshold configurable without code change |
| 8 | Run evaluation tests | All T18.x tests pass |

**Atomic Sub-tasks:**
1. Per-chunk metric computation
2. Session quality score aggregation
3. Rolling window threshold check
4. SSE warning emission
5. Client warning UI
6. Threshold configuration

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| No speech in chunk | speech_ratio=0; do not trigger low_speech_ratio warning (expected for silence) |
| All chunks low quality | Escalate to critical; persist warning |
| Threshold changed mid-session | Apply new threshold from next chunk |
| SSE client disconnected | Buffer warnings; deliver on reconnect |
| Metric computation fails | Log error; skip metric for this chunk |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Metric computation pattern: pure functions per metric
- Aggregation pattern: rolling window with configurable size
- Observer pattern: warning events via SSE
- Configuration pattern: thresholds in config file

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`audio_quality.py`, `quality_warning.py`)
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

**Quality Metrics Schema (per chunk):**
```yaml
Stream: audio.quality
Fields:
  session_id: "550e8400-e29b-41d4-a716-446655440000"
  sequence: "5"
  snr_db: "18.5"
  speech_ratio: "0.72"
  clipping_rate: "0.001"
  lufs: "-22.5"
```

**Session Quality Score (persisted to DB):**
```sql
UPDATE sessions
SET audio_quality = 0.82
WHERE id = '550e8400-e29b-41d4-a716-446655440000';
```

**SSE Warning Event:**
```yaml
Event: audio_warning
Data:
  session_id: "550e8400-e29b-41d4-a716-446655440000"
  warning_type: "low_snr"
  severity: "warning"
  message: "Audio SNR below threshold (8.2 dB < 15 dB). Consider repositioning the device."
  metric_value: 8.2
  threshold: 15.0
  timestamp: "2026-09-12T10:05:00Z"
```

**Quality Thresholds Config:**
```yaml
# config/quality_thresholds.yaml
snr:
  degraded: 20.0    # dB — below this = degraded
  warning: 15.0     # dB — below this = warning
  critical: 10.0    # dB — below this = critical
speech_ratio:
  min: 0.1          # below this = no speech (not a warning)
clipping:
  warning: 0.01     # above this = clipping warning
  critical: 0.05    # above this = clipping critical
rolling_window:
  size: 5           # chunks
  min_chunks: 3     # minimum chunks before evaluating
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `QUALITY_SNR_DEGRADED_DB` | float | SNR degraded threshold | `20.0` |
| `QUALITY_SNR_WARNING_DB` | float | SNR warning threshold | `15.0` |
| `QUALITY_SNR_CRITICAL_DB` | float | SNR critical threshold | `10.0` |
| `QUALITY_CLIPPING_WARNING` | float | Clipping warning threshold | `0.01` |
| `QUALITY_CLIPPING_CRITICAL` | float | Clipping critical threshold | `0.05` |
| `QUALITY_ROLLING_WINDOW_SIZE` | int | Rolling window size (chunks) | `5` |
| `QUALITY_MIN_CHUNKS` | int | Min chunks before evaluation | `3` |
| `QUALITY_WARNING_COOLDOWN_S` | int | Min seconds between warnings | `30` |

**Third-Party Integration Contracts:**
- S17: Receives processed chunk with VAD regions
- S16: SSE endpoint for warning delivery
- S07: Session table for `audio_quality` persistence
- Client PWA (S15): Warning UI display

**Version Pins:**
- numpy >= 1.26.0
- SSE-Starlette >= 1.0

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T18.1 | U | `pytest tests/test_audio_quality.py::test_metrics_computation -v` | Metrics computed correctly on fixtures of known SNR |
| T18.2 | I | `pytest tests/test_audio_quality.py::test_subthreshold_warning -v` | Sub-threshold audio triggers warning event on SSE |
| T18.3 | I | `pytest tests/test_audio_quality.py::test_warning_in_client_ui -v` | Warning appears in client UI within 10s of onset |
| T18.4 | I | `pytest tests/test_audio_quality.py::test_quality_score_persisted -v` | Session `audio_quality` persisted on completion |
| T18.5 | U | `pytest tests/test_audio_quality.py::test_threshold_configurable -v` | Threshold configurable without code change |

**Test Case Details (Given/When/Then):**

**T18.1 — Metrics computed correctly on known fixtures**
- **Given:** audio fixtures with known SNR (5dB, 15dB, 25dB, 40dB)
- **When:** per-chunk metrics are computed
- **Then:** SNR values match expected within ±2dB tolerance

**T18.2 — Sub-threshold audio triggers SSE warning**
- **Given:** a session with rolling window SNR below 15dB threshold
- **When:** the quality evaluator processes the sub-threshold chunk
- **Then:** a `audio_warning` event is emitted on the SSE stream

**T18.3 — Warning appears in client UI within 10s**
- **Given:** an SSE connection is active for a session
- **When:** audio quality drops below threshold
- **Then:** the warning message appears in the client UI within 10 seconds

**T18.4 — Session audio_quality persisted on completion**
- **Given:** a session completes processing
- **When:** the session quality score is computed
- **Then:** `sessions.audio_quality` is updated with the aggregated score

**T18.5 — Threshold configurable without code change**
- **Given:** threshold config file is modified
- **When:** the quality evaluator reads the new config
- **Then:** new thresholds are applied without code redeployment

**Verification Commands:**
```bash
uv run pytest tests/test_audio_quality.py -v -k "S18" && \
uv run mypy --strict src/services/audio_quality/ && \
uv run ruff check src/services/audio_quality/
```

**Exit Criteria:**
- [ ] T18.1 passes — metrics computed correctly
- [ ] T18.2 passes — sub-threshold triggers SSE warning
- [ ] T18.3 passes — warning in client UI within 10s
- [ ] T18.4 passes — session quality persisted
- [ ] T18.5 passes — thresholds configurable
- [ ] Badly-positioned microphone surfaced to user during lecture

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Rolling window must have minimum chunks before evaluating — single-chunk spike should not trigger warning
- Warning cooldown prevents spam — but must not suppress genuine continuous issues
- `speech_ratio=0` is not a quality issue (silence between chunks) — do not warn
- Clipping rate computation must use peak detection, not RMS
- Quality score aggregation must weight recent chunks more heavily

**Fallback Instructions:**
- If metric computation fails: skip chunk, log error, continue
- If SSE delivery fails: buffer warnings, deliver on reconnect
- If threshold config unreadable: use defaults
- If session quality cannot be computed: set `audio_quality=NULL` (not 0)

**Rollback Procedure:**
- No database migrations — quality score is nullable float
- Stop quality evaluator: disable in worker config
- Feature flag: `QUALITY_WARNINGS_ENABLED=false` disables SSE warnings
- Threshold config can be reverted to defaults

---

### 9. Observability (if applicable)

**Metrics Added:**
- `audio_quality_snr_db`: histogram of per-chunk SNR values
- `audio_quality_speech_ratio`: histogram of per-chunk speech ratios
- `audio_quality_clipping_rate`: histogram of per-chunk clipping rates
- `audio_quality_warnings_total`: counter of warnings emitted (labels: type, severity)
- `audio_quality_score`: histogram of session quality scores
- `audio_quality_rolling_window_size`: gauge of current window size

**Tracing/Logging:**
- Span: `quality.compute_chunk_metrics` with attributes (session_id, sequence, snr, speech_ratio)
- Span: `quality.evaluate_threshold` with attributes (session_id, status, warning_triggered)
- Log: INFO on quality score persisted
- Log: WARN on threshold breach
- Log: ERROR on metric computation failure

**Alerts:**
- Warning rate > 50% of sessions: systemic audio quality issue
- Quality score consistently < 0.3: recording environment problem

---

### 10. Exit Checklist

- [ ] All tests pass (T18.1–T18.5)
- [ ] Per-chunk metrics computed correctly
- [ ] Session quality score aggregated and persisted
- [ ] SSE warnings emitted for sub-threshold quality
- [ ] Warning appears in client UI within 10s
- [ ] Thresholds configurable without code change
- [ ] Badly-positioned microphone surfaced during lecture

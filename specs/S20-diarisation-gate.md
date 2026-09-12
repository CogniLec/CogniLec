# S20 ⛔ — Anonymous Diarisation & Transcript Completion (HARD GATE)
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Apply anonymous speaker diarisation (SPK_A, SPK_B) to utterances, enforce NFR-S4 biometric non-linkability, and validate the end-to-end ingestion spine — the HARD GATE that must pass before any downstream block proceeds.

**CRITICAL: This is a HARD GATE stage. The end-to-end ingestion spine must work on real audio before any downstream block (S21+) can begin. T20.5 is the gate test.**

**Component Boundaries:**
- **Allowed:** `src/services/diarisation/`, `src/workers/diarisation_worker.py`, `tests/test_diarisation.py`, `tests/test_e2e_gate.py`, `tests/fixtures/audio/`
- **Off-limits:** Embedding (S25), segmentation (S30), note synthesis (S44), any downstream block

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| pyannote.audio | 3.x | Speaker diarisation |
| torch | 2.5.x | Model runtime |
| SQLAlchemy | 2.0.52 | DB persistence |
| faster-whisper | 1.1.x | ASR (dependency for gate test) |

---

### 2. State Machine & Domain Schemas

**Diarisation State:**
```
NOT_STARTED → PROCESSING → COMPLETE → TAGGED
                    ↓
                  FAILED
                    ↓
              DISABLED (optional mode)
```

**Speaker Tag Schema:**
```python
# src/services/diarisation/models.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from enum import Enum

class SpeakerTag(str, Enum):
    """Session-scoped anonymous speaker tags.
    NEVER linked across sessions.
    NEVER used as biometric identifiers.
    DROPPED at note synthesis (A2 input has no speaker info).
    """
    SPK_A = "SPK_A"
    SPK_B = "SPK_B"
    SPK_C = "SPK_C"
    SPK_D = "SPK_D"
    SPK_E = "SPK_E"
    UNKNOWN = "UNKNOWN"

class DiarisationResult(BaseModel):
    session_id: UUID
    speaker_count: int = Field(..., ge=0)
    utterance_speaker_map: dict[int, str]  # sequence → speaker_tag
    processing_time_ms: int
    model_name: str = "pyannote/speaker-diarization-3.1"

class NFRS4AuditResult(BaseModel):
    """NFR-S4 compliance audit result."""
    session_id: UUID
    voiceprints_found: int = Field(0, description="Must be 0")
    embeddings_persisted: int = Field(0, description="Must be 0")
    biometric_templates: int = Field(0, description="Must be 0")
    speaker_tags_session_scoped: bool = Field(True, description="Must be True")
    cross_session_linkage_possible: bool = Field(False, description="Must be False")
    compliant: bool
    audit_timestamp: datetime

class NonLinkabilityAssertion(BaseModel):
    """NFR-S4: Biometric non-linkability assertion."""
    session_a_id: UUID
    session_b_id: UUID
    tags_session_a: list[str]
    tags_session_b: list[str]
    overlap_count: int = Field(0, description="Must be 0 — tags are session-local")
    linkable: bool = Field(False, description="Must be False")
    assertion_passed: bool
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Implement pyannote.audio diarisation step | Speaker tags assigned to utterances |
| 2 | Implement `speaker_tag` persistence to `utterances` table | Tags stored in `utterances.speaker_tag` |
| 3 | Implement NFR-S4 verification: no voiceprint/embedding/biometric storage | Audit passes (T20.2) |
| 4 | Implement session-scoped tag isolation | Tags not linkable across sessions (T20.3) |
| 5 | Implement diarisation-disabled mode | Pipeline completes without diarisation (T20.4) |
| 6 | **Implement end-to-end gate test (T20.5)** | **Record → chunks → preprocess → ASR → complete transcript** |
| 7 | Run NFR-S4 biometric non-linkability verification | All audit checks pass |
| 8 | **Run gate test on real audio** | **T20.5 PASSES — downstream blocks may begin** |

**Atomic Sub-tasks:**
1. pyannote.audio integration
2. Speaker tag persistence
3. NFR-S4 schema and storage audit
4. Session-scoped tag isolation
5. Diarisation-disabled mode
6. End-to-end gate test
7. Biometric non-linkability verification

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| pyannote model unavailable | Run without diarisation; all tags remain UNKNOWN |
| Single speaker session | All utterances tagged SPK_A |
| Many speakers (>5) | Cap at SPK_A–SPK_E; rest tagged UNKNOWN |
| Diarisation fails | Log error; utterances retain no speaker tag; pipeline continues |
| NFR-S4 violation detected | FAIL GATE — no downstream blocks proceed |
| Gate test (T20.5) fails | FAIL GATE — investigate and fix before proceeding |
| Session has no speech | Diarisation produces no tags; pipeline completes |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Gate pattern: T20.5 must pass before downstream blocks
- Audit pattern: NFR-S4 compliance verification
- Isolation pattern: session-scoped tags, never cross-session
- Optional pattern: diarisation can be disabled without breaking pipeline

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`diarisation_worker.py`, `nfr_s4_audit.py`)
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

**Diarisation Worker Interface:**
```python
# src/services/diarisation/worker.py
class DiarisationWorker:
    async def process_session(
        self,
        session_id: UUID,
        enable_diarisation: bool = True,
    ) -> DiarisationResult:
        """
        Apply diarisation to all utterances in a session.
        Tags are session-scoped only. Never persisted as biometric data.
        """

    async def assign_speaker_tags(
        self,
        session_id: UUID,
        audio_path: str,
    ) -> dict[int, str]:
        """Assign anonymous speaker tags to utterances based on audio."""
```

**NFR-S4 Audit Interface:**
```python
# src/services/diarisation/nfr_s4_audit.py
class NFRS4Audit:
    async def audit_session(self, session_id: UUID) -> NFRS4AuditResult:
        """Verify no voiceprint/embedding/biometric data is persisted."""

    async def audit_database_schema(self) -> list[str]:
        """Verify no biometric columns exist in any table."""

    async def audit_storage(self) -> list[str]:
        """Verify no biometric files exist in any bucket."""

    async def verify_non_linkability(
        self,
        session_a_id: UUID,
        session_b_id: UUID,
    ) -> NonLinkabilityAssertion:
        """Verify speaker tags from two sessions are not linkable."""
```

**Speaker Tag Persistence:**
```sql
-- Add speaker_tag column to utterances (migration)
ALTER TABLE utterances
ADD COLUMN speaker_tag VARCHAR(10);

-- Update utterance with speaker tag
UPDATE utterances
SET speaker_tag = 'SPK_A'
WHERE session_id = '550e8400-...' AND sequence = 0;

-- NFR-S4: Verify no biometric columns exist
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'utterances'
  AND column_name LIKE '%voiceprint%'
  OR column_name LIKE '%biometric%'
  OR column_name LIKE '%embedding%';
-- Result must be empty
```

**End-to-End Gate Test Flow:**
```yaml
# T20.5 Gate Test — E2E Ingestion Spine
# Steps:
1. Create session via API (POST /sessions)
2. Record audio on device (simulated: use fixture audio)
3. Upload chunks via presigned URL (PUT chunks to lis-audio)
4. Preprocess chunks (S17 chain: resample → denoise → VAD)
5. ASR transcription (S19: faster-whisper → utterances)
6. Diarisation (S20: pyannote → speaker tags)
7. Verify complete transcript in DB-1:
   - All utterances present
   - Word-level timestamps present
   - Confidence scores present
   - Speaker tags present (if diarisation enabled)
   - Session status = 'transcribed'
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `DIARISATION_ENABLED` | bool | Enable diarisation | `true` |
| `DIARISATION_MODEL` | string | pyannote model ID | `pyannote/speaker-diarization-3.1` |
| `DIARISATION_MAX_SPEAKERS` | int | Max speakers to detect | `5` |
| `NFR_S4_AUDIT_ENABLED` | bool | Enable NFR-S4 audit | `true` |
| `GATE_TEST_AUDIO_PATH` | string | Path to gate test audio fixture | `tests/fixtures/audio/lecture_60min.opus` |
| `GATE_TEST_SESSION_ID` | string | Session ID for gate test | (generated) |

**Third-Party Integration Contracts:**
- pyannote.audio 3.x: speaker diarisation
- S19: ASR worker (dependency for gate test)
- S17: Preprocessing chain (dependency for gate test)
- S16: Chunk upload (dependency for gate test)
- S14: Object storage (dependency for gate test)
- PostgreSQL (S07): Utterance persistence

**Version Pins:**
- pyannote.audio >= 3.1.0
- torch >= 2.5.0
- faster-whisper >= 1.1.0

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T20.1 | I | `pytest tests/test_diarisation.py::test_speaker_tags_assigned -v` | Speaker tags assigned; multiple distinct speakers detected |
| T20.2 | S | `pytest tests/test_diarisation.py::test_no_biometric_data -v` | No voiceprint/embedding/biometric template persisted anywhere (NFR-S4) |
| T20.3 | S | `pytest tests/test_diarisation.py::test_tags_not_linkable -v` | Speaker tags from two sessions not linkable |
| T20.4 | I | `pytest tests/test_diarisation.py::test_diarisation_disabled -v` | Pipeline completes with diarisation disabled |
| T20.5 | E | `pytest tests/test_e2e_gate.py::test_ingestion_spine_e2e -v` | **GATE: record → chunks → preprocess → ASR → complete transcript** |

**Test Case Details (Given/When/Then):**

**T20.1 — Speaker tags assigned; multiple speakers detected**
- **Given:** a discussion-heavy session with 3+ speakers
- **When:** diarisation processes the session
- **Then:** utterances have speaker tags (SPK_A, SPK_B, SPK_C); at least 3 distinct tags assigned

**T20.2 — No voiceprint, embedding, or biometric template persisted (NFR-S4)**
- **Given:** a session has been processed with diarisation
- **When:** the NFR-S4 audit scans all database tables and storage buckets
- **Then:** no voiceprint, embedding, or biometric template is found anywhere; `compliant=true`

**T20.3 — Speaker tags from two sessions are not linkable**
- **Given:** two sessions processed by diarisation
- **When:** the non-linkability assertion compares speaker tags
- **Then:** `overlap_count=0`; `linkable=false`; tags are session-local only

**T20.4 — Pipeline completes with diarisation disabled**
- **Given:** `DIARISATION_ENABLED=false`
- **When:** a session is processed end-to-end
- **Then:** pipeline completes; all utterances have `speaker_tag=NULL`; transcript is complete

**T20.5 — GATE: End-to-end ingestion spine (CRITICAL)**
- **Given:** a real audio recording (60-minute lecture fixture)
- **When:** the full ingestion spine runs: create session → upload chunks → preprocess → ASR → diarisation
- **Then:**
  - Session status = `transcribed`
  - All utterances present in DB-1
  - Each utterance has: `text`, `start_ms`, `end_ms`, `confidence`, `words` (word-level timestamps)
  - Each utterance has: `session_id`, `subject_id`, `embed_model_ver`
  - Speaker tags present (SPK_A, etc.) if diarisation enabled
  - Session `audio_quality` is set
  - **No errors in the pipeline**
  - **Processing completes within reasonable time (RTF < 2.0 for full session)**

**NFR-S4 Biometric Non-Linkability Verification Procedure:**
```python
# tests/test_diarisation.py — NFR-S4 verification

async def test_no_biometric_data():
    """NFR-S4: No voiceprint, embedding or biometric template persisted anywhere."""

    # 1. Scan database schema for biometric columns
    biometric_columns = await db.execute("""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE column_name LIKE '%voiceprint%'
           OR column_name LIKE '%biometric%'
           OR column_name LIKE '%speaker_embedding%'
           OR column_name LIKE '%d_vector%'
           OR column_name LIKE '%x_vector%'
    """)
    assert len(biometric_columns) == 0, f"Biometric columns found: {biometric_columns}"

    # 2. Scan storage buckets for biometric files
    for bucket in ["lis-audio", "lis-uploads", "lis-generated", "lis-exports"]:
        objects = await storage.list_objects(bucket, prefix="")
        biometric_objects = [
            o for o in objects
            if "voiceprint" in o.key.lower()
            or "embedding" in o.key.lower()
            or "biometric" in o.key.lower()
            or "speaker_model" in o.key.lower()
        ]
        assert len(biometric_objects) == 0, f"Biometric files in {bucket}: {biometric_objects}"

    # 3. Verify speaker_tags are session-scoped only
    tags = await db.execute("""
        SELECT speaker_tag, COUNT(DISTINCT session_id) as session_count
        FROM utterances
        WHERE speaker_tag IS NOT NULL
        GROUP BY speaker_tag
        HAVING COUNT(DISTINCT session_id) > 1
    """)
    assert len(tags) == 0, f"Speaker tags linked across sessions: {tags}"

    # 4. Verify tags are dropped at note synthesis (check A2 input schema)
    # A2 input has no speaker_tag field — verified by schema
```

**Verification Commands:**
```bash
# Run diarisation tests
uv run pytest tests/test_diarisation.py -v -k "S20"

# Run NFR-S4 audit
uv run pytest tests/test_diarisation.py::test_no_biometric_data -v
uv run pytest tests/test_diarisation.py::test_tags_not_linkable -v

# Run end-to-end gate test
uv run pytest tests/test_e2e_gate.py -v -k "T20.5"

# Run full gate verification
uv run pytest tests/test_e2e_gate.py tests/test_diarisation.py -v

# Type check
uv run mypy --strict src/services/diarisation/ src/workers/diarisation_worker.py

# Lint
uv run ruff check src/services/diarisation/ src/workers/diarisation_worker.py
```

**Exit Criteria:**
- [ ] T20.1 passes — speaker tags assigned, multiple speakers detected
- [ ] T20.2 passes — **NFR-S4: no biometric data anywhere** (schema + storage audit)
- [ ] T20.3 passes — speaker tags not linkable across sessions
- [ ] T20.4 passes — pipeline completes with diarisation disabled
- [ ] **T20.5 passes — GATE: end-to-end ingestion spine works on real audio**
- [ ] NFR-S4 biometric non-linkability verified
- [ ] **All downstream blocks (S21+) may begin ONLY after T20.5 passes**

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- pyannote.audio requires HuggingFace token for model download — must be configured
- Speaker diarisation is computationally expensive — may increase processing time
- NFR-S4 audit must check BOTH database schema AND storage — one without the other is insufficient
- Speaker tags must be session-scoped — if tags leak across sessions, NFR-S4 is violated
- Diarisation is optional — pipeline must complete without it (T20.4)
- Gate test (T20.5) uses real audio — must have fixture available
- `speaker_tag` column must be nullable — diarisation may be disabled

**Fallback Instructions:**
- If pyannote unavailable: diarisation disabled; all tags remain NULL; pipeline continues
- If NFR-S4 audit fails: **DO NOT proceed to downstream blocks** — investigate and fix
- If gate test fails: **DO NOT proceed to downstream blocks** — this is a HARD GATE
- If diarisation is slow: consider disabling for initial deployment; enable later

**Rollback Procedure:**
- Drop `speaker_tag` column: `ALTER TABLE utterances DROP COLUMN speaker_tag`
- Remove diarisation worker: `docker compose stop diarisation`
- Feature flag: `DIARISATION_ENABLED=false` disables diarisation
- **Gate test failure requires investigation — no rollback, must fix forward**

---

### 9. Observability (if applicable)

**Metrics Added:**
- `diarisation_sessions_total`: counter of sessions processed (labels: success, diarisation_enabled)
- `diarisation_speaker_count`: histogram of speakers detected per session
- `diarisation_latency_ms`: histogram of processing time
- `nfr_s4_audit_total`: counter of NFR-S4 audits (labels: compliant=true/false)
- `nfr_s4_violation_total`: counter of NFR-S4 violations
- `gate_test_total`: counter of gate test runs (labels: passed=true/false)
- `gate_test_latency_ms`: histogram of gate test duration

**Tracing/Logging:**
- Span: `diarisation.process_session` with attributes (session_id, speaker_count, latency_ms)
- Span: `nfr_s4.audit` with attributes (session_id, compliant, voiceprints_found)
- Span: `gate.test_e2e` with attributes (session_id, passed, duration_ms)
- Log: INFO on diarisation complete
- Log: INFO on NFR-S4 audit passed
- Log: **ERROR on NFR-S4 violation — CRITICAL**
- Log: **INFO on gate test passed — downstream blocks may proceed**
- Log: **ERROR on gate test failed — downstream blocks blocked**

**Alerts:**
- **NFR-S4 violation detected: CRITICAL — halt downstream processing**
- **Gate test failed: CRITICAL — halt downstream processing**
- Diarisation failure rate > 10%: model or GPU issue

---

### 10. Exit Checklist

- [ ] All tests pass (T20.1, T20.2, T20.3, T20.4, **T20.5**)
- [ ] Speaker tags assigned to utterances
- [ ] **NFR-S4: no voiceprint/embedding/biometric data anywhere** (verified by audit)
- [ ] Speaker tags session-scoped, not linkable across sessions
- [ ] Pipeline completes with diarisation disabled
- [ ] **T20.5 GATE PASSES: end-to-end ingestion spine works on real audio**
- [ ] **NFR-S4 biometric non-linkability assertion verified**
- [ ] **All downstream blocks (S21+) may begin**
- [ ] Tags dropped at note synthesis (verified by A2 schema)

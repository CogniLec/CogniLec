# S49 — MVP Acceptance (HARD GATE)
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Encode SRS acceptance criteria AC-1 through AC-11 as an executable pytest suite run against a real deployment with real recorded lectures, execute a pilot with 3–5 real users for two weeks of actual lectures, and collect structured feedback. **All eleven AC tests must pass before the decision point for continuing to Blocks 9–13.**

**Component Boundaries:**
- **Allowed:** `tests/test_ac_acceptance.py`, `tests/test_pilot.py`, `tests/conftest.py`, `scripts/run_ac_tests.sh`, `scripts/pilot_deploy.sh`, `docs/pilot_feedback.md`, pilot configuration files
- **Off-limits:** All source code modifications unless a test reveals a critical defect requiring fix; Block 9–13 code; production deployment without passing AC tests

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| pytest | 8.x | Acceptance test execution |
| testcontainers | 4.6.x | Container orchestration for test environment |
| Docker Compose | 2.x | Deployment orchestration for pilot |
| ffmpeg | 6.x | Audio processing for test fixtures |
| Real lecture recordings | N/A | Test data for AC tests |

---

### 2. State Machine & Domain Schemas

**Acceptance Test Gate State Machine:**
```
NOT_STARTED → RUNNING → ALL_PASS → DECISION_POINT (proceed to Block 9-13)
                    ↓
                ANY_FAIL → BLOCKED (fix defects, re-run AC tests)
                    ↓
                ALL_PASS → DECISION_POINT
```

**Pilot Deployment State Machine:**
```
AC_TESTS_PASS → DEPLOY_PILOT → COLLECT_FEEDBACK → ANALYZE → DECISION (proceed or fix)
                    ↓
                FEEDBACK_NEGATIVE → FIX_DEFECTS → RE_DEPLOY
```

**Acceptance Criteria Mapping:**
```python
# tests/test_ac_acceptance.py
AC_CRITERIA = {
    "AC-1": "Subject declared, session recorded against it",
    "AC-2": "60-min lecture → complete transcript, WER within S06 gate",
    "AC-3": "Two-topic session split into two ordered segments",
    "AC-4": "Topic across three sessions recognised as one",
    "AC-5": "Off-topic chatter excluded; relevant student question retained",
    "AC-6": "Notes post-session only; no DB-2 row without DB-1",
    "AC-7": "Every note section traces to source utterances and timestamps",
    "AC-8": "Primary LLM killed → completes via fallback",
    "AC-9": "All tiers exhausted → failed, fully reprocessable",
    "AC-10": "No cross-subject retrieval",
    "AC-11": "Processing < 15 min P90",
}
```

**Pilot Feedback Schema:**
```python
# docs/pilot_feedback.py
from pydantic import BaseModel, Field

class PilotUserFeedback(BaseModel):
    user_id: str
    session_id: str
    subject: str
    notes_usability_rating: int = Field(ge=1, le=5)  # 1=unusable, 5=excellent
    transcript_accuracy_rating: int = Field(ge=1, le=5)
    search_quality_rating: int = Field(ge=1, le=5)
    would_use_again: bool
    comments: str = Field(default="")
    completion_time_seconds: int
    processing_latency_seconds: int

class PilotReport(BaseModel):
    total_sessions: int
    avg_usability_rating: float
    avg_transcript_accuracy: float
    avg_search_quality: float
    would_use_again_percentage: float
    common_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
```

**State Transition Rules:**
- NOT_STARTED → RUNNING: when AC test suite is invoked
- RUNNING → ALL_PASS: all 11 AC tests pass
- RUNNING → ANY_FAIL: any AC test fails; block continues until all pass
- ALL_PASS → DEPLOY_PILOT: pilot deployment proceeds
- DEPLOY_PILOT → COLLECT_FEEDBACK: 2-week pilot period
- COLLECT_FEEDBACK → ANALYZE: pilot feedback analysis
- ANALYZE → DECISION: proceed to Block 9–13 if feedback positive

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `tests/test_ac_acceptance.py` with AC-1 through AC-11 test cases | File created, tests are syntactically valid |
| 2 | Set up test environment with Docker Compose (real deployment) | All services start and pass health checks |
| 3 | Load real lecture recordings as test fixtures | Audio files present in test data directory |
| 4 | Run AC-1: subject declared, session recorded against it | T49.1 passes |
| 5 | Run AC-2: 60-min lecture → transcript, WER within gate | T49.2 passes |
| 6 | Run AC-3: two-topic session split into two segments | T49.3 passes |
| 7 | Run AC-4: topic across three sessions recognised as one | T49.4 passes |
| 8 | Run AC-5: off-topic chatter excluded, student question retained | T49.5 passes |
| 9 | Run AC-6: notes post-session only, no orphaned DB rows | T49.6 passes |
| 10 | Run AC-7: note sections trace to utterances and timestamps | T49.7 passes |
| 11 | Run AC-8: primary LLM killed → completes via fallback | T49.8 passes |
| 12 | Run AC-9: all tiers exhausted → failed, reprocessable | T49.9 passes |
| 13 | Run AC-10: no cross-subject retrieval | T49.10 passes |
| 14 | Run AC-11: processing < 15 min P90 | T49.11 passes |
| 15 | Verify all 11 AC tests pass | ALL_PASS gate reached |
| 16 | Deploy pilot environment | Pilot services running |
| 17 | Onboard 3–5 pilot users | Users registered and trained |
| 18 | Collect feedback over 2 weeks | Feedback report generated |
| 19 | Analyze feedback and make go/no-go decision | Decision documented |

**Atomic Sub-tasks:**
1. Acceptance test suite (AC-1 through AC-11)
2. Test environment setup (Docker Compose with real deployment)
3. Real lecture recording fixtures
4. Pilot deployment automation
5. Feedback collection mechanism
6. Feedback analysis and reporting
7. Go/no-go decision framework

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| AC test fails on first run | Log failure details, fix defect, re-run failing test only |
| Test environment crashes during AC run | Restart environment, re-run full suite |
| Real lecture recording corrupt | Use backup recording, log fixture issue |
| Pilot user drops out | Replace with backup user, continue pilot |
| Pilot feedback negative | Document issues, fix defects, extend pilot |
| WER exceeds S06 gate | Block AC-2, investigate ASR model, re-run |
| Processing time exceeds 15 min | Block AC-11, investigate bottleneck, optimize |
| Cross-subject retrieval detected | Block AC-10, fix subject isolation, re-run |
| LLM fallback fails | Block AC-8, fix fallback chain, re-run |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Gate pattern: all 11 AC tests must pass before proceeding
- Fixture pattern: real lecture recordings as pytest fixtures
- Report pattern: structured pilot feedback collection and analysis
- Decision framework: clear go/no-go criteria with documented rationale

**Naming & Style Guidelines:**
- Test files: `test_ac_acceptance.py`, `test_pilot.py`
- Test functions: `test_ac_N_description` (e.g., `test_ac_1_subject_declared`)
- Fixtures: `conftest.py` with session-scoped fixtures for test environment
- Reports: Markdown files with structured data

**Code Splitting Metrics:**
- Max test function length: 50 lines
- Max fixture complexity: simple, composable fixtures
- Max report section length: 100 lines

**Type Safety:**
- Test functions typed with pytest fixtures
- Feedback models typed with Pydantic v2
- Report data typed with TypedDict or Pydantic models

---

### 5. API & Interface Contracts

**Acceptance Test Commands:**
```bash
# Run all AC tests
uv run pytest tests/test_ac_acceptance.py -v --tb=long

# Run single AC test
uv run pytest tests/test_ac_acceptance.py::test_ac_1_subject_declared -v

# Run with coverage
uv run pytest tests/test_ac_acceptance.py -v --cov=src --cov-report=html
```

**Pilot Deployment Command:**
```bash
# Deploy pilot environment
docker compose -f docker-compose.pilot.yaml up -d

# Check pilot health
docker compose -f docker-compose.pilot.yaml ps

# Collect feedback
python scripts/collect_feedback.py --pilot-id=pilot_001
```

**Test Data Requirements:**
```yaml
# tests/fixtures/real_lectures.yaml
lectures:
  - id: lecture_01
    subject: "Organic Chemistry"
    duration_minutes: 60
    format: wav
    path: tests/fixtures/lecture_01.wav
    transcript_ground_truth: tests/fixtures/lecture_01_ground_truth.txt
    topics:
      - "Reaction Kinetics"
      - "Equilibrium"
    has_off_topic: true
    has_student_questions: true

  - id: lecture_02
    subject: "Organic Chemistry"
    duration_minutes: 45
    format: wav
    path: tests/fixtures/lecture_02.wav
    transcript_ground_truth: tests/fixtures/lecture_02_ground_truth.txt
    topics:
      - "Reaction Kinetics"
      - "Thermodynamics"
    has_off_topic: false

  - id: lecture_03
    subject: "Linear Algebra"
    duration_minutes: 55
    format: wav
    path: tests/fixtures/lecture_03.wav
    transcript_ground_truth: tests/fixtures/lecture_03_ground_truth.txt
    topics:
      - "Eigenvalues"
      - "Matrix Decomposition"
    has_off_topic: true
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `AC_TEST_ENV` | string | Test environment name | `ci` |
| `PILOT_DEPLOY_PATH` | string | Pilot deployment directory | `/opt/lis/pilot` |
| `PILOT_USERS_FILE` | string | Pilot user configuration | `tests/fixtures/pilot_users.json` |
| `WER_THRESHOLD` | float | WER threshold for AC-2 | `0.15` |
| `PROCESSING_TIME_THRESHOLD_MIN` | int | Processing time threshold for AC-11 | `15` |
| `PILOT_DURATION_DAYS` | int | Pilot duration in days | `14` |
| `FEEDBACK_FORM_URL` | string | Feedback collection URL | `https://forms.example.com/lis-pilot` |

**Test Environment Requirements:**
- PostgreSQL with pgvector extension
- Redis for caching and event broker
- ASR service (Whisper) running
- LLM service with primary and fallback models
- Embedding service (TEI)
- All pipeline services running

**Version Pins:**
- Docker Compose file pinned to specific image tags
- Test fixtures pinned to specific recordings
- Pilot environment pinned to same versions as AC test environment

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T49.1 | E | `pytest tests/test_ac_acceptance.py::test_ac_1_subject_declared -v` | Subject declared, session recorded against it |
| T49.2 | E | `pytest tests/test_ac_acceptance.py::test_ac_2_transcript_wer -v` | 60-min lecture → complete transcript, WER within gate |
| T49.3 | E | `pytest tests/test_ac_acceptance.py::test_ac_3_topic_split -v` | Two-topic session split into two ordered segments |
| T49.4 | E | `pytest tests/test_ac_acceptance.py::test_ac_4_topic_recognition -v` | Topic across three sessions recognised as one |
| T49.5 | E | `pytest tests/test_ac_acceptance.py::test_ac_5_offtopic_filtering -v` | Off-topic chatter excluded; relevant student question retained |
| T49.6 | E | `pytest tests/test_ac_acceptance.py::test_ac_6_notes_post_session -v` | Notes post-session only; no DB-2 row without DB-1 |
| T49.7 | E | `pytest tests/test_ac_acceptance.py::test_ac_7_note_tracing -v` | Every note section traces to source utterances and timestamps |
| T49.8 | E | `pytest tests/test_ac_acceptance.py::test_ac_8_llm_fallback -v` | Primary LLM killed → completes via fallback |
| T49.9 | E | `pytest tests/test_ac_acceptance.py::test_ac_9_all_tiers_exhausted -v` | All tiers exhausted → failed, fully reprocessable |
| T49.10 | E | `pytest tests/test_ac_acceptance.py::test_ac_10_no_cross_subject -v` | No cross-subject retrieval |
| T49.11 | P | `pytest tests/test_ac_acceptance.py::test_ac_11_processing_time -v` | Processing < 15 min P90 |
| T49.12 | M | `python scripts/collect_feedback.py --pilot-id=pilot_001` | Pilot users report notes are usable for study |

**Test Case Details (Given/When/Then):**

**T49.1 — AC-1: Subject declared, session recorded against it**
- **Given:** a subject "Organic Chemistry" is declared in the system
- **When:** a session is recorded and associated with the subject
- **Then:** the session exists in the database with the correct subject_id, and the subject contains the session in its session list

**T49.2 — AC-2: 60-min lecture → complete transcript, WER within gate**
- **Given:** a real 60-minute lecture recording (lecture_01.wav) with ground truth transcript
- **When:** `process_session()` is invoked on the recording
- **Then:** a complete transcript is generated, WER (Word Error Rate) is ≤ 0.15 (S06 gate threshold), and transcript covers the full duration

**T49.3 — AC-3: Two-topic session split into two ordered segments**
- **Given:** a lecture covering "Reaction Kinetics" and "Equilibrium" (two distinct topics)
- **When:** `process_session()` is invoked
- **Then:** the transcript is split into two segments, each segment corresponds to one topic, and segments are ordered chronologically

**T49.4 — AC-4: Topic across three sessions recognised as one**
- **Given:** three sessions (lecture_01, lecture_02) all cover "Reaction Kinetics"
- **When:** the system processes all three sessions and a search query for "Reaction Kinetics" is executed
- **Then:** results from all three sessions are returned as belonging to the same topic, with consistent topic labeling

**T49.5 — AC-5: Off-topic chatter excluded; relevant student question retained**
- **Given:** a lecture containing off-topic chatter (e.g., "Did you watch the game last night?") and a relevant student question (e.g., "Can you explain that mechanism again?")
- **When:** `process_session()` is invoked
- **Then:** off-topic chatter is excluded from notes, but the relevant student question is retained in the notes

**T49.6 — AC-6: Notes post-session only; no DB-2 row without DB-1**
- **Given:** a session with no prior notes
- **When:** `process_session()` is invoked
- **Then:** notes are created only after session processing completes, and no note_section row exists without a corresponding utterance row (DB-2 without DB-1)

**T49.7 — AC-7: Every note section traces to source utterances and timestamps**
- **Given:** generated notes from a processed session
- **When:** a note section is inspected
- **Then:** each note section has traceable source_utterance_ids and timestamps pointing back to the original utterances

**T49.8 — AC-8: Primary LLM killed → completes via fallback**
- **Given:** a running session with primary LLM available
- **When:** the primary LLM process is killed mid-processing
- **Then:** the pipeline detects the failure, switches to the fallback LLM, and completes processing successfully

**T49.9 — AC-9: All tiers exhausted → failed, fully reprocessable**
- **Given:** a running session with all LLM tiers (primary, secondary, tertiary) disabled or unavailable
- **When:** `process_session()` is invoked
- **Then:** the pipeline attempts all tiers, marks the session as FAILED, and the session can be fully reprocessed from scratch when tiers become available

**T49.10 — AC-10: No cross-subject retrieval**
- **Given:** transcripts from Subject A (Organic Chemistry) and Subject B (Linear Algebra)
- **When:** a search query is executed with `subject_id="subj_A"`
- **Then:** only results from Subject A are returned; no results from Subject B appear

**T49.11 — AC-11: Processing < 15 min P90**
- **Given:** 10 real lecture recordings (60 minutes each)
- **When:** all 10 are processed end-to-end
- **Then:** P90 processing time is < 15 minutes

**T49.12 — Pilot feedback**
- **Given:** 3–5 pilot users using the system for 2 weeks with real lectures
- **When:** structured feedback survey is collected
- **Then:** average usability rating ≥ 3.5/5, ≥ 80% of users would use again, no critical issues reported

**Verification Commands:**
```bash
# Full AC test suite
docker compose -f docker-compose.test.yaml up -d && \
uv run pytest tests/test_ac_acceptance.py -v --tb=long --junitxml=reports/ac_results.xml

# Pilot deployment
docker compose -f docker-compose.pilot.yaml up -d && \
python scripts/pilot_deploy.sh --pilot-id=pilot_001

# Feedback collection
python scripts/collect_feedback.py --pilot-id=pilot_001 --output=reports/pilot_feedback.json

# Final verification
uv run pytest tests/test_ac_acceptance.py -v -k "S49" && \
echo "ALL 11 AC TESTS PASSED - PROCEED TO BLOCK 9-13"
```

**Exit Criteria (HARD GATE):**
- [ ] T49.1 passes — AC-1: subject declared, session recorded
- [ ] T49.2 passes — AC-2: transcript WER within S06 gate
- [ ] T49.3 passes — AC-3: two-topic session split into segments
- [ ] T49.4 passes — AC-4: topic across sessions recognised as one
- [ ] T49.5 passes — AC-5: off-topic excluded, student question retained
- [ ] T49.6 passes — AC-6: notes post-session, no orphaned DB rows
- [ ] T49.7 passes — AC-7: note sections trace to utterances and timestamps
- [ ] T49.8 passes — AC-8: primary LLM killed → fallback completes
- [ ] T49.9 passes — AC-9: all tiers exhausted → failed, reprocessable
- [ ] T49.10 passes — AC-10: no cross-subject retrieval
- [ ] T49.11 passes — AC-11: processing < 15 min P90
- [ ] T49.12 passes — pilot feedback positive (usability ≥ 3.5, ≥ 80% would use again)

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Real lecture recordings vary in quality; WER may fluctuate — use multiple recordings to ensure robustness
- LLM fallback kill test (T49.8) may cause non-deterministic behavior; use SIGKILL not SIGTERM for clean failure
- Pilot users may not provide feedback; incentivize with structured feedback form and regular check-ins
- Cross-subject retrieval test (T49.10) requires isolated test data; ensure no shared embeddings between subjects
- Processing time (T49.11) varies by hardware; benchmark on target deployment hardware
- DB-2 without DB-1 test (T49.6) requires careful transaction ordering; ensure notes are created atomically with session completion

**Fallback Instructions:**
- If AC-2 fails (WER too high): check ASR model version, ensure audio quality is sufficient, re-run with different recording
- If AC-8 fails (fallback doesn't work): check fallback chain configuration, ensure secondary LLM is available
- If AC-9 fails (reprocessing doesn't work): check session reset logic, ensure all cache entries are cleared
- If AC-11 fails (processing too slow): profile bottleneck, optimize critical path, consider hardware upgrade
- If pilot feedback negative: document specific issues, prioritize fixes, extend pilot period

**Rollback Procedure:**
- If any AC test fails: stop pilot, fix defect, re-run full AC suite
- If pilot feedback negative: rollback pilot deployment, document issues, schedule fix iteration
- If critical defect found during pilot: rollback deployment, issue hotfix, re-deploy
- Feature flags: disable specific features via environment variables if they cause AC test failures
- No code rollback needed if AC tests pass — proceed to Block 9–13

---

### 9. Observability (if applicable)

**Metrics Added:**
- `ac_test_result`: gauge of AC test results (1=pass, 0=fail) for each AC criterion
- `ac_test_duration_seconds`: duration of each AC test execution
- `pilot_sessions_total`: counter of pilot sessions processed
- `pilot_feedback_submitted_total`: counter of feedback submissions
- `pilot_usability_rating`: gauge of average pilot usability rating
- `processing_time_p90_seconds`: gauge of P90 processing time across sessions

**Tracing/Logging:**
- Log: INFO on each AC test start and completion with result
- Log: WARNING on AC test failure with failure details
- Log: ERROR on critical defect discovery during pilot
- Log: INFO on pilot feedback submission with anonymized ratings
- Log: INFO on go/no-go decision with rationale

**Alerts:**
- Any AC test fails: block pilot deployment, notify team
- Pilot usability rating drops below 3.0: investigate issues
- Pilot feedback submission rate < 50%: encourage participation
- Processing time P90 exceeds 15 minutes: investigate performance

---

### 10. Exit Checklist

- [ ] All 11 AC tests pass (T49.1 through T49.11)
- [ ] Pilot feedback collected from 3–5 users over 2 weeks
- [ ] Average pilot usability rating ≥ 3.5/5
- [ ] ≥ 80% of pilot users would use the system again
- [ ] No critical issues reported during pilot
- [ ] **HARD GATE PASSED: Proceed to Blocks 9–13**
- [ ] Decision documented with rationale
- [ ] Any remaining issues prioritized for future blocks

**⚠️ HARD GATE NOTICE:**
> This stage is a HARD GATE. All eleven AC tests (T49.1–T49.11) MUST pass before the decision point for continuing to Blocks 9–13. If any AC test fails, the pipeline is BLOCKED until the defect is fixed and all tests pass. Pilot feedback must be positive (usability ≥ 3.5, ≥ 80% would use again) before proceeding. No exceptions.

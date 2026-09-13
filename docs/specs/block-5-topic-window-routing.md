# Block 5 — Topic Window & Session Routing: S33–S35 Specification

> **Generated from:** `LIS-implementation-plan-v1.md` lines 539–578
> **Codebase snapshot:** 2026-09-12
> **Status:** Living spec — implementer-owned

---

## Table of Contents

- [S33 — Greeting Keywords & Topic Window](#s33--greeting-keywords--topic-window)
- [S34 — Transition Cue Detection](#s34--transition-cue-detection)
- [S35 — Session Type Classification & Routing](#s35--session-type-classification--routing)
- [Cross-cutting concerns](#cross-cutting-concerns)

---

## S33 — Greeting Keywords & Topic Window

### 1. Stage Identity

| Field | Value |
|---|---|
| **ID** | S33 |
| **Name** | Greeting Keywords & Topic Window |
| **Block** | 5 — Topic Window & Session Routing |
| **Owner** | TBD |
| **Estimate** | TBD |

### 2. Context

S33 exists because the system needs two early-stage signals that fire before the full post-session pipeline (S30) completes:

1. **Greeting detection** — a session-start/boundary heuristic. Configurable keywords ("good morning", "good afternoon", "good evening", and localized equivalents) mark where a lecture begins. **Crucially, greeting detection must never set or influence `speaker_tag` or `is_relevant`** — this reverses the original design and is a hard invariant (FR-2.3, FR-2.4, FR-2.5, FR-2.9).

2. **Provisional topic window** — a lightweight clustering pass over the first 10 minutes of transcript to surface early topic candidates to the client. This is provisional only; the post-session full-transcript pass (S30) remains authoritative (FR-2.9).

**Predecessor:** S30 (Topic Clustering) must be operational because the provisional window reuses its embedding and clustering infrastructure. The provisional pass is a *preview* of the S30 pipeline, not an independent implementation.

### 3. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| S30 — Topic Clustering | Upstream | BERTopic pipeline, UMAP+HDBSCAN, `topics` persistence |
| `config/models.yaml` | External | EMBEDDING_MODEL, EMBEDDING_DIM for provisional vectorization |
| `src/eval/harness.py` | External | `run_eval(DatasetType.SEGMENTATION)` for authority proof (T33.4) |
| `src/db/models/session.py` | Schema | `Session.session_type` field (existing, check-constrained) |
| `src/db/models/utterance.py` | Schema | Utterance embeddings, `outlier_score` |
| `src/db/models/segment.py` | Schema | Segment `boundary_score` for provisional segmentation |

### 4. Requirements Traced

| Req ID | Verbatim (from plan) |
|---|---|
| FR-2.3 | Greeting keywords detected as session-start/boundary signal |
| FR-2.4 | Greeting detection never sets or influences speaker_tag or relevance |
| FR-2.5 | Configurable greeting keyword set per language |
| FR-2.9 | Post-session full-transcript pass (S30) remains authoritative; provisional result is provisional |
| NFR-P2 | Provisional topics available within 60s of the 10-minute mark |

### 5. Interface Contracts

#### 5.1 SQL DDL — No new tables

S33 does not introduce new tables. It writes to existing tables:

```sql
-- Provisional topic rows written to `topics` table (created by S30).
-- Must carry a `provisional` flag to distinguish from final topics.
ALTER TABLE topics ADD COLUMN provisional BOOLEAN NOT NULL DEFAULT TRUE;
-- Final topics from S30 have provisional = FALSE (or are updated in-place).
```

#### 5.2 Pydantic Schemas

```python
# src/ml/greeting.py — new file


class GreetingMatch(BaseModel):
    """A single greeting keyword match within a transcript."""

    utterance_id: uuid.UUID
    seq: int
    matched_keyword: str
    language: str
    start_ms: int
    end_ms: int


class GreetingDetectionResult(BaseModel):
    """Result of greeting detection across a session."""

    session_id: uuid.UUID
    matches: list[GreetingMatch]
    has_greeting: bool  # True if at least one greeting detected
    session_start_boundary: (
        int | None
    )  # seq of utterance where session starts (None if no greeting)
```

```python
# src/ml/provisional_window.py — new file


class ProvisionalTopic(BaseModel):
    """A topic candidate from the first-10-minute provisional pass."""

    label: str | None  # None until S31 labelling runs
    keywords: list[str]
    centroid: list[float]  # embedding dimension matches EMBEDDING_DIM
    utterance_count: int
    start_seq: int
    end_seq: int


class ProvisionalWindowResult(BaseModel):
    """Result of the provisional topic window pass."""

    session_id: uuid.UUID
    window_minutes: int  # default 10
    topics: list[ProvisionalTopic]
    utterances_in_window: int
    generated_at: datetime
    is_authoritative: bool = False  # Always False; FR-2.9
```

#### 5.3 API Paths

No new REST endpoints. Provisional results are delivered via an internal event (see §5.4).

#### 5.4 Event Names

```python
# Published to Valkey/Redis stream after provisional window completes
event_name = "session.provisional_topics_ready"
payload = {
    "session_id": str(uuid),
    "subject_id": str(uuid),
    "topic_count": int,
    "utterances_in_window": int,
    "generated_at": "ISO-8601",
}
```

#### 5.5 Prompt Text & Version

No LLM prompt for greeting detection (regex/keyword matching only). Provisional clustering uses the same embedding model as S30 — no new prompt.

### 6. Implementation Notes

#### 6.1 Greeting Keyword Detector

- **Algorithm:** Regex-based, case-insensitive, with word-boundary anchors.
- **Config key:** `config/greeting_keywords.yaml` (new file)

```yaml
# config/greeting_keywords.yaml
version: "1.0"
keywords:
  en:
    - pattern: "\\bgood\\s+(morning|afternoon|evening)\\b"
    - pattern: "\\bhello\\b"
    - pattern: "\\bwelcome\\b"
    - pattern: "\\bstart(?:ing)?\\s+(?:the\\s+)?(?:lecture|class|session|today)\\b"
  es:
    - pattern: "\\bbuen(?:os|as)\\s+(dias|tardes|noches)\\b"
  # ... additional languages as needed
```

- **Invariants (MUST NOT):**
  - Must never write to `utterances.speaker_tag`
  - Must never write to `utterances.is_relevant`
  - Must never modify `utterances.filter_reason`
  - These are hard negative assertions — T33.2 validates them.

#### 6.2 Provisional Window Pass

- **Algorithm:**
  1. Filter utterances to first 10 minutes (by `start_ms` from utterance 0).
  2. Use existing `UtteranceRepository.vector_query` for embeddings (reuse S06 model).
  3. Run mini-BERTopic: UMAP → HDBSCAN on the windowed subset.
  4. Write provisional topics to `topics` with `provisional = TRUE`.
  5. Publish `session.provisional_topics_ready` event.

- **Config keys:**
  - `PROVISIONAL_WINDOW_MINUTES` = 10 (default)
  - `PROVISIONAL_UMAP_N_NEIGHBORS` = 15 (default, smaller than full pass for speed)
  - `PROVISIONAL_HDBSCAN_MIN_CLUSTER_SIZE` = 3 (default)

- **Failure handling:**
  - If window contains < 5 utterances: skip provisional pass, log warning, do not publish event.
  - If clustering produces 0 topics: publish event with `topic_count = 0`.
  - If embedding model is unavailable: log error, skip, pipeline continues (provisional is non-blocking).

#### 6.3 FR-2.9 Authority

- Provisional results are stored separately or flagged — they MUST NOT be surfaced as final topics.
- The post-session S30 pass overwrites provisional data.
- `ProvisionalWindowResult.is_authoritative` is always `False`.

### 7. Test Specification

#### T33.1 — Greeting keywords detected across phrasings and languages
```
Given:  a session transcript with utterances containing "Good morning everyone"
        and "Welcome to today's lecture"
When:   greeting detection runs
Then:   GreetingDetectionResult.has_greeting is True
        GreetingDetectionResult.matches contains ≥ 2 entries
        Each match has matched_keyword, language, and valid utterance_id
```

#### T33.2 — Greeting detection never sets speaker_tag or relevance (explicit negative)
```
Given:  a session transcript with greeting utterances
When:   greeting detection runs
Then:   NO utterance row has speaker_tag modified by this stage
        NO utterance row has is_relevant modified by this stage
        NO utterance row has filter_reason modified by this stage
        (Assert by snapshotting utterance state before/after and diffing)
```

#### T33.3 — Provisional topics available within 60s of the 10-minute mark (NFR-P2)
```
Given:  a session transcript with > 10 minutes of content
When:   the 10-minute mark is reached
Then:   ProvisionalWindowResult is generated and published
        Total wall-clock time from 10-minute mark to event publication < 60 seconds
        (Use pytest-benchmark or monotonic clock assertion)
```

#### T33.4 — Provisional result differs from final result, and final is authoritative (FR-2.9)
```
Given:  a real session transcript where provisional clustering produces different
        topic boundaries than full-session clustering (S30)
When:   both provisional and full passes complete
Then:   ProvisionalWindowResult.is_authoritative is False
        The final topics table does NOT contain provisional = TRUE rows
        The provisional result is NOT surfaced in the client UI after S30 completes
```

#### T33.5 — Session shorter than 10 minutes completes without error
```
Given:  a session transcript with 3 minutes of content
When:   greeting detection and provisional window pass run
Then:   greeting detection completes normally (may or may not find greetings)
        provisional window pass completes without error
        ProvisionalWindowResult.utterances_in_window == total utterances
        No exception raised; pipeline continues to S30
```

### 8. Observability

| Type | Name | Description |
|---|---|---|
| Metric | `lis.greeting.matches_total` | Counter of greeting matches by language |
| Metric | `lis.provisional.window.duration_seconds` | Histogram of provisional pass wall time |
| Metric | `lis.provisional.topics_count` | Gauge of provisional topics generated per session |
| Span | `greeting_detection` | OpenTelemetry span covering keyword scan |
| Span | `provisional_window_pass` | OpenTelemetry span covering the 10-min clustering |
| Log | `provisional_window_skipped` | Warning when window has < 5 utterances |
| Log | `provisional_clustering_empty` | Info when HDBSCAN finds 0 clusters |

### 9. Rollback

- **Migration down:** Drop `topics.provisional` column if added.
- **Code revert:** Remove `src/ml/greeting.py`, `src/ml/provisional_window.py`, `config/greeting_keywords.yaml`.
- **Feature flag:** `FEATURE_PROVISIONAL_WINDOW` (env var) — when `false`, skip provisional pass entirely. Greeting detection can be independently disabled via `FEATURE_GREETING_DETECTION`.
- **Data cleanup:** Delete rows from `topics` where `provisional = TRUE`.

### 10. Exit Checklist

- [ ] Greeting keyword detector implemented and configurable
- [ ] Provisional window pass produces topics within 60s of 10-minute mark
- [ ] T33.1 through T33.5 all pass
- [ ] Greeting detection never modifies `speaker_tag` or `is_relevant` (T33.2 verified)
- [ ] Provisional results are flagged and non-authoritative (FR-2.9)
- [ ] Observability metrics/spans wired
- [ ] Feature flags documented
- [ ] **Signed off:** ___________  Date: ___________

---

## S34 — Transition Cue Detection

### 1. Stage Identity

| Field | Value |
|---|---|
| **ID** | S34 |
| **Name** | Transition Cue Detection |
| **Block** | 5 — Topic Window & Session Routing |
| **Owner** | TBD |
| **Estimate** | TBD |

### 2. Context

S34 provides a **second independent signal** for boundary detection, complementing S28's sequential segmentation. Transition cues are explicit forward references in speech — "next we'll cover", "moving on to", "that completes", "before the break" — that a lecturer uses to signal topic shifts. They are curated for high precision (recall may be low), and they **boost** boundary scores in S28 rather than overriding them.

This stage exists because:
1. S28's embedding-similarity approach can miss explicit verbal transitions.
2. LLM confirmation of candidates adds a second validation layer.
3. Cues must earn their place — T34.3 requires they measurably improve P_k versus S29 baseline.

**Predecessors:** S28 (Boundary Detection) and S31 (Topic Labelling & Keyword Extraction). S28 provides the boundary scores that S34 boosts. S31 provides topic labels that can inform cue confirmation.

### 3. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| S28 — Boundary Detection | Upstream | Produces `segments.boundary_score` that cues boost |
| S31 — Topic Labelling | Upstream | Topic labels inform LLM confirmation of cue candidates |
| `src/eval/harness.py` | External | `run_eval(DatasetType.SEGMENTATION)` for P_k comparison (T34.3) |
| `src/db/models/segment.py` | Schema | `Segment.boundary_score` field to be boosted |
| `src/core/config.py` | Config | LLM_TIER1_MODEL for confirmation step |
| S05 corpus | External | Hand-marked lectures for precision evaluation (T34.2) |

### 4. Requirements Traced

| Req ID | Verbatim (from plan) |
|---|---|
| FR-2.8 | Transition cues detected in transcript text |
| ML-9 | High-precision pattern set with LLM confirmation |

### 5. Interface Contracts

#### 5.1 SQL DDL — Schema extension

```sql
-- Add cue_metadata column to segments to track which cues contributed to a boundary
ALTER TABLE segments ADD COLUMN cue_metadata JSONB DEFAULT NULL;
-- Example: {"cue_matches": ["moving on to", "next we'll cover"], "boost_applied": 0.15}
```

#### 5.2 Pydantic Schemas

```python
# src/ml/transition_cues.py — new file


class CuePattern(BaseModel):
    """A single transition cue pattern."""

    id: str  # e.g. "moving_on"
    pattern: str  # regex pattern
    language: str
    category: str  # "forward_reference" | "completion" | "temporal"
    weight: float  # 0.0-1.0, confidence weight for score boosting


class CueMatch(BaseModel):
    """A detected cue in transcript text."""

    utterance_id: uuid.UUID
    seq: int
    pattern_id: str
    matched_text: str
    position_start: int  # character offset in utterance text
    position_end: int


class TransitionCueResult(BaseModel):
    """Result of transition cue detection for a session."""

    session_id: uuid.UUID
    matches: list[CueMatch]
    total_matches: int
    detected_at: datetime


class BoundaryBoost(BaseModel):
    """A boost applied to a segment boundary score."""

    segment_id: uuid.UUID
    original_score: float
    boosted_score: float
    cue_count: int
    patterns_matched: list[str]
```

#### 5.3 API Paths

No new REST endpoints. Cue results are applied internally during the segmentation pipeline.

#### 5.4 Event Names

```python
# Published when cues are detected and boosts applied
event_name = "session.transition_cues_detected"
payload = {
    "session_id": str(uuid),
    "cue_count": int,
    "boosted_boundary_count": int,
    "detected_at": "ISO-8601",
}
```

#### 5.5 Prompt Text & Version

**LLM confirmation prompt (Tier 1):**

```
You are validating whether detected text patterns represent genuine topic transitions
in a lecture transcript.

Given the following text segments with detected transition cues, determine if each
cue represents a REAL topic transition (the speaker is genuinely moving to a new topic)
versus a FALSE POSITIVE (the cue phrase is used in a different context).

For each cue, respond with:
- "confirmed": the cue indicates a real topic transition
- "rejected": the cue is a false positive
- "uncertain": cannot determine

Session context: {topic_labels}

Cues to validate:
{cue_matches_with_surrounding_text}

Respond in JSON format: [{"cue_id": "...", "verdict": "confirmed|rejected|uncertain", "reason": "..."}]
```

**Prompt version:** `v1.0`
**Model tier:** LLM_TIER1_MODEL (Phi-3-mini-4k-instruct)

### 6. Implementation Notes

#### 6.1 Pattern Set

- **Config file:** `config/transition_cues.yaml` (new file)

```yaml
version: "1.0"
cues:
  - id: "moving_on"
    pattern: "\\b(moving\\s+on\\s+to|let'?s\\s+move\\s+on\\s+to|now\\s+we'?ll\\s+(?:look\\s+at|cover|discuss))\\b"
    language: "en"
    category: "forward_reference"
    weight: 0.8
  - id: "next_topic"
    pattern: "\\b(next\\s+(?:we'?ll|let'?s|I'?ll|topic\\s+is)|the\\s+next\\s+(?:topic|subject|thing))\\b"
    language: "en"
    category: "forward_reference"
    weight: 0.75
  - id: "completes_section"
    pattern: "\\b(that\\s+completes|that\\s+covers|that\\s+(?:wraps\\s+up|finishes)|so\\s+that'?s\\s+(?:the\\s+)?end\\s+of)\\b"
    language: "en"
    category: "completion"
    weight: 0.85
  - id: "break_reference"
    pattern: "\\b(before\\s+(?:the\\s+)?break|after\\s+(?:the\\s+)?break|let'?s\\s+take\\s+a\\s+break)\\b"
    language: "en"
    category: "temporal"
    weight: 0.9
  # Additional patterns for high-precision detection
  - id: "today_we_cover"
    pattern: "\\btoday\\s+we'?ll\\s+(?:be\\s+)?(?:covering|looking\\s+at|discussing|talking\\s+about)\\b"
    language: "en"
    category: "forward_reference"
    weight: 0.7
```

- **Design principle:** High precision, low recall. Each pattern must be validated on the S05 corpus before inclusion.

#### 6.2 Detection Algorithm

1. **Pattern matching phase:** For each utterance, run all patterns from `config/transition_cues.yaml`. Collect matches with surrounding context (±2 utterances).
2. **LLM confirmation phase:** Batch confirmed candidates (max 20 per call) through the confirmation prompt. Use `LLM_TIER1_MODEL` via the LLM ladder (S37).
3. **Score boosting phase:** For each confirmed cue at utterance `seq`, find the S28 segment boundary nearest to that utterance. Boost `boundary_score` by the cue's `weight`:

```
boosted_score = original_score + (cue.weight * BOOST_MULTIPLIER)
BOOST_MULTIPLIER = 0.2 (configurable)
```

4. **Persistence:** Write `cue_metadata` JSONB to the affected segment row.

- **Config keys:**
  - `TRANSITION_CUE_BOOST_MULTIPLIER` = 0.2
  - `TRANSITION_CUE_MAX_CANDIDATES_PER_LLM_CALL` = 20
  - `TRANSITION_CUE_MIN_UTOVERANCE_CONTEXT` = 2

- **Failure handling:**
  - Pattern matching failure: log error, skip cue detection, S28 boundaries remain unchanged.
  - LLM confirmation failure (Tier 5 exhausted): apply pattern-only boost without LLM confirmation. Log warning. Do not block pipeline.
  - Invalid regex in config: fail fast at startup with clear error message.

#### 6.3 "Boosts, Not Overrides" Invariant

Cues **must not** create new boundaries — they only boost existing S28 boundary scores. If S28 did not detect a boundary near a cue location, the cue is logged but not applied. This prevents false splits (T34.4).

### 7. Test Specification

#### T34.1 — Each pattern matches its intended phrasings
```
Given:  a list of test phrases for each cue pattern
        e.g. "Moving on to the next section", "Let's move on to calculus"
When:   each phrase is matched against its corresponding pattern
Then:   every test phrase produces a match
        matched_text is correct
        No unrelated phrases produce matches (pattern specificity check)
```

#### T34.2 — Precision > 0.85 on the S05 corpus
```
Given:  the S05 hand-marked lecture corpus (30 sessions)
        with ground-truth transition cue annotations
When:   the full cue detection pipeline (pattern + LLM confirmation) runs
Then:   precision (true_positives / (true_positives + false_positives)) > 0.85
        recall is recorded but no threshold enforced
        Results are reproducible across runs (same corpus, same config)
```

#### T34.3 — Adding cues improves P_k versus S29 baseline
```
Given:  S28 segmentation results on S05 corpus (baseline P_k from S29)
When:   transition cue boosting is applied to the same segmentation
Then:   P_k with cues < P_k without cues (improvement)
        The improvement is statistically significant (p < 0.05, paired t-test)
        WindowDiff is also recorded alongside P_k
```

#### T34.4 — Cue in middle of coherent topic does not force spurious split
```
Given:  a session segment where a transition cue appears mid-topic
        e.g. "Moving on to the next example" within a single-topic explanation
When:   cue detection and boosting run
Then:   no new segment boundary is created at the cue location
        the existing boundary score is boosted but remains below the split threshold
        the segment remains contiguous and unbroken
```

### 8. Observability

| Type | Name | Description |
|---|---|---|
| Metric | `lis.cue.pattern_matches_total` | Counter of raw pattern matches by pattern_id |
| Metric | `lis.cue.llm_confirmed_total` | Counter of LLM-confirmed cues |
| Metric | `lis.cue.boost_applied_total` | Counter of boundary boosts applied |
| Metric | `lis.cue.boost_magnitude` | Histogram of score boost magnitudes |
| Span | `transition_cue_detection` | OpenTelemetry span covering pattern scan + LLM confirmation |
| Span | `cue_llm_confirmation` | Child span for the LLM confirmation call |
| Log | `cue_llm_fallback` | Warning when LLM confirmation fails, pattern-only boost applied |
| Log | `cue_no_nearby_boundary` | Debug when cue found but no S28 boundary within window |

### 9. Rollback

- **Migration down:** Drop `segments.cue_metadata` column if added.
- **Code revert:** Remove `src/ml/transition_cues.py`, `config/transition_cues.yaml`.
- **Feature flag:** `FEATURE_TRANSITION_CUES` (env var) — when `false`, cue detection and boosting are skipped entirely. S28 boundaries remain as-is.
- **Data cleanup:** Set `segments.cue_metadata = NULL` for all affected rows.

### 10. Exit Checklist

- [ ] Cue pattern set defined and validated on S05 corpus
- [ ] LLM confirmation step implemented with fallback
- [ ] Boundary score boosting implemented (boosts, not overrides)
- [ ] T34.1 through T34.4 all pass
- [ ] P_k improvement demonstrated versus S29 baseline
- [ ] Observability metrics/spans wired
- [ ] Feature flag documented
- [ ] **Signed off:** ___________  Date: ___________

---

## S35 — Session Type Classification & Routing

### 1. Stage Identity

| Field | Value |
|---|---|
| **ID** | S35 |
| **Name** | Session Type Classification & Routing |
| **Block** | 5 — Topic Window & Session Routing |
| **Owner** | TBD |
| **Estimate** | TBD |

### 2. Context

S35 classifies each session as `content`, `syllabus`, or `mixed` from its transcript, then routes segments to the appropriate database partition. This is a high-consequence decision (v2.0 §4.1) implemented as an ensemble vote with an operator override at session start.

**Why ensemble?** Misclassification has asymmetric costs — routing syllabus content to the content DB loses structural information, while routing content to the syllabus DB pollutes the structured syllabus. Ensemble voting with disagreement-flagging (T35.4) avoids the worst failure mode: confident wrong guesses.

**Mixed sessions** are the common case, not an exception. A first lecture covering syllabus then teaching is typical — S35 routes segments individually, not the whole session (FR-2.21).

**Predecessors:** S34 (Transition Cue Detection) for enhanced boundaries, and S36 (Local LLM Serving) for the classification LLM. The existing `Session.session_type` field (already check-constrained to `content|syllabus|mixed` in `src/db/models/session.py:28-30`) is the persistence target.

### 3. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| S34 — Transition Cue Detection | Upstream | Enhanced segment boundaries for per-segment classification |
| S36 — Local LLM Serving | Upstream | Tier 1 LLM for ensemble component |
| `src/db/models/session.py` | Schema | `Session.session_type` field (existing) |
| `src/db/models/segment.py` | Schema | Segment rows for per-segment routing |
| `src/db/repositories/session_repo.py` | Code | `SessionRepository.update_status()` pattern for session_type updates |
| `src/db/repositories/segment_repo.py` | Code | `SegmentRepository.bulk_insert()` for segment routing |
| `src/api/schemas/session.py` | Schema | `SessionCreate.session_type` for operator override |
| Dual Postgres FDW (S04) | External | DB-2 (content) and DB-3 (syllabus) are separate databases |
| `config/models.yaml` | External | LLM_TIER1_MODEL for classification ensemble |

### 4. Requirements Traced

| Req ID | Verbatim (from plan) |
|---|---|
| FR-2.20 | Session classified as content / syllabus / mixed from transcript |
| FR-2.21 | Mixed sessions route segments individually to appropriate DB |

### 5. Interface Contracts

#### 5.1 SQL DDL — Schema extension

```sql
-- Add classification metadata to sessions
ALTER TABLE sessions ADD COLUMN classification_confidence FLOAT DEFAULT NULL;
ALTER TABLE sessions ADD COLUMN classification_method VARCHAR(20) DEFAULT NULL;
-- Values: 'ensemble', 'operator_override', 'llm_only', 'rule_only'
ALTER TABLE sessions ADD COLUMN classification_details JSONB DEFAULT NULL;
-- Example: {
--   "ensemble_vote": {"content": 2, "syllabus": 1, "mixed": 0},
--   "llm_verdict": "content",
--   "rule_verdict": "mixed",
--   "final": "mixed"
-- }

-- Add route_target to segments for per-segment routing
ALTER TABLE segments ADD COLUMN route_target VARCHAR(20) DEFAULT NULL;
-- Values: 'db_2' (content), 'db_3' (syllabus), NULL (not yet classified)
```

#### 5.2 Pydantic Schemas

```python
# src/ml/session_classifier.py — new file


class ClassificationVote(BaseModel):
    """A single vote from one classifier component."""

    component: str  # "llm", "rule_keyword", "rule_structure"
    prediction: str  # "content" | "syllabus" | "mixed"
    confidence: float  # 0.0-1.0


class SessionClassification(BaseModel):
    """Full classification result for a session."""

    session_id: uuid.UUID
    votes: list[ClassificationVote]
    final_type: str  # "content" | "syllabus" | "mixed"
    confidence: float  # aggregate confidence
    method: str  # "ensemble" | "operator_override" | "llm_only"
    details: dict[str, Any]  # raw vote data for audit
    classified_at: datetime


class SegmentRoute(BaseModel):
    """Routing decision for a single segment."""

    segment_id: uuid.UUID
    route_target: str  # "db_2" | "db_3"
    classification: str  # "content" | "syllabus"
    confidence: float


class SessionRoutePlan(BaseModel):
    """Complete routing plan for a session's segments."""

    session_id: uuid.UUID
    session_type: str  # "content" | "syllabus" | "mixed"
    segment_routes: list[SegmentRoute]
    created_at: datetime
```

#### 5.3 API Paths

```python
# Existing endpoint modified — operator override at session creation
POST /sessions/
# Request body already supports session_type field:
class SessionCreate(BaseModel):
    subject_id: uuid.UUID
    session_type: str = "content"  # Operator can set to 'syllabus' or 'mixed'
```

```python
# New endpoint — post-classification override
PATCH / sessions / {session_id} / classification


# Request body:
class ClassificationOverride(BaseModel):
    session_type: str  # "content" | "syllabus" | "mixed"
    reason: str  # Required audit trail


# Response: SessionResponse with updated session_type
```

#### 5.4 Event Names

```python
# Published after classification completes
event_name = "session.classified"
payload = {
    "session_id": str(uuid),
    "session_type": str,  # "content" | "syllabus" | "mixed"
    "confidence": float,
    "method": str,
    "classified_at": "ISO-8601",
}

# Published when re-routing occurs after misclassification correction
event_name = "session.rerouted"
payload = {
    "session_id": str(uuid),
    "previous_type": str,
    "new_type": str,
    "segments_moved": int,
    "rerouted_at": "ISO-8601",
}
```

#### 5.5 Prompt Text & Version

**LLM classification prompt (Tier 1):**

```
You are classifying a lecture session transcript into one of three categories:

- "content": The session is primarily teaching/explaining material. The lecturer
  is presenting concepts, working through examples, or discussing a topic in depth.
- "syllabus": The session is primarily administrative or structural. The lecturer
  is outlining the course structure, explaining grading, listing topics to be covered,
  or discussing logistics.
- "mixed": The session contains significant portions of both content teaching and
  syllabus/administrative material.

Analyze the following transcript excerpt (first 15 minutes or full transcript if shorter):

{transcript_text}

Consider:
1. What proportion of the transcript is teaching vs. administrative?
2. Are there clear transitions between administrative and teaching sections?
3. What is the primary purpose of the session?

Respond in JSON:
{
  "classification": "content" | "syllabus" | "mixed",
  "confidence": 0.0-1.0,
  "content_ratio": 0.0-1.0,
  "reasoning": "brief explanation"
}
```

**Prompt version:** `v1.0`
**Model tier:** LLM_TIER1_MODEL

### 6. Implementation Notes

#### 6.1 Ensemble Classification

Three classifier components vote:

| Component | Method | Config Key |
|---|---|---|
| LLM classifier | LLM_TIER1_MODEL via prompt | `CLASSIFIER_LLM_ENABLED` = true |
| Rule-based keyword | Keyword density analysis | `CLASSIFIER_RULE_KEYWORD_ENABLED` = true |
| Rule-based structure | Transcript structure heuristics | `CLASSIFIER_RULE_STRUCTURE_ENABLED` = true |

**Voting logic:**
1. If operator override was set at session creation (`SessionCreate.session_type != "content"` default), use it directly — method = `operator_override`.
2. Otherwise, collect votes from all enabled components.
3. If all agree → `final_type` = consensus, `method` = `ensemble`.
4. If majority agree → `final_type` = majority, `method` = `ensemble`.
5. If no majority → `final_type` = `mixed` (safe default), `method` = `ensemble`, confidence = 0.0, **flag session for review** (T35.4).

**Rule-based keyword classifier:**
- Compute `syllabus_keyword_density` = count(syllabus keywords) / total words
- Syllabus keywords: "syllabus", "grading", "assessment", "schedule", "office hours", "prerequisites", "textbook", "curriculum"
- If density > 0.02 → syllabus; < 0.005 → content; else → uncertain

**Rule-based structure classifier:**
- Look for list-like patterns ("first...", "second...", "third...")
- Look for date/deadline mentions
- Look for short utterances with high question density
- Score: high list density + date mentions + short utterances → syllabus

#### 6.2 Segment-Level Routing

For `mixed` sessions, each segment is classified independently:

```python
async def route_segments(
    session: Session,
    segments: list[Segment],
    utterances: list[Utterance],
) -> SessionRoutePlan:
    routes = []
    for segment in segments:
        seg_utterances = [u for u in utterances if segment.start_utt <= u.id <= segment.end_utt]
        seg_text = " ".join(u.text for u in seg_utterances)
        classification = classify_segment(seg_text)  # reuse ensemble
        route_target = "db_2" if classification == "content" else "db_3"
        routes.append(
            SegmentRoute(
                segment_id=segment.id,
                route_target=route_target,
                classification=classification,
                confidence=classification.confidence,
            )
        )
    return SessionRoutePlan(
        session_id=session.id, session_type=session.session_type, segment_routes=routes
    )
```

**Routing persistence:** Write `segments.route_target` to each segment. Downstream consumers (S40+ note generation) read `route_target` to determine which database to query.

#### 6.3 Misclassification Correction

When operator corrects a classification via `PATCH /sessions/{session_id}/classification`:
1. Update `sessions.session_type`, `classification_method = 'operator_override'`.
2. Re-run segment routing with the new type.
3. Publish `session.rerouted` event with `segments_moved` count.
4. Log the correction for future classifier improvement.

#### 6.4 Config Keys

| Key | Default | Description |
|---|---|---|
| `CLASSIFIER_LLM_ENABLED` | `true` | Enable LLM voting component |
| `CLASSIFIER_RULE_KEYWORD_ENABLED` | `true` | Enable keyword rule component |
| `CLASSIFIER_RULE_STRUCTURE_ENABLED` | `true` | Enable structure rule component |
| `CLASSIFIER_MIN_CONFIDENCE` | `0.6` | Below this, flag for review |
| `CLASSIFIER_SYLLABUS_KEYWORD_DENSITY_HIGH` | `0.02` | Threshold for syllabus rule |
| `CLASSIFIER_SYLLABUS_KEYWORD_DENSITY_LOW` | `0.005` | Threshold for content rule |
| `CLASSIFIER_MIXED_DEFAULT` | `true` | Default to 'mixed' on disagreement |

#### 6.5 Failure Handling

- LLM classification failure (Tier 5 exhausted): fall back to rule-based only. Set `method = 'rule_only'`. Log warning.
- All classifiers fail: set `session_type = 'content'` (safe default), `confidence = 0.0`, flag for review.
- Database routing failure: log error, do not move segments. Session remains in current state until retry.
- Re-routing failure: log error, publish `session.rerouted` with `segments_moved = 0`.

### 7. Test Specification

#### T35.1 — Classification accuracy > 0.90 on labelled sessions
```
Given:  a set of labelled sessions (content, syllabus, mixed) from S05 corpus
When:   the ensemble classifier runs on each session
Then:   overall accuracy > 0.90
        accuracy is reported per class (content, syllabus, mixed)
        confusion matrix is logged for analysis
        No class has recall < 0.80 (per-class minimum)
```

#### T35.2 — Mixed session routes syllabus segments to DB-3 and content segments to DB-2 (FR-2.21)
```
Given:  a session classified as 'mixed' with segments:
        segment_1: syllabus content (0-5 min)
        segment_2: teaching content (5-45 min)
        segment_3: syllabus wrap-up (45-50 min)
When:   segment-level routing runs
Then:   segment_1.route_target = 'db_3'
        segment_2.route_target = 'db_2'
        segment_3.route_target = 'db_3'
        All segments from one transcript are routed correctly
        No segment is left unclassified (route_target is not NULL)
```

#### T35.3 — Operator override takes precedence over classification
```
Given:  a session where the ensemble classifier predicts 'content'
        but the operator set session_type = 'syllabus' at creation
When:   classification and routing run
Then:   session.session_type = 'syllabus'
        session.classification_method = 'operator_override'
        all segments are routed to 'db_3'
        the LLM vote is recorded but overridden
```

#### T35.4 — Ensemble disagreement flags session for review
```
Given:  a session where classifiers disagree:
        LLM: "content" (confidence 0.7)
        Rule-keyword: "syllabus" (confidence 0.6)
        Rule-structure: "mixed" (confidence 0.5)
When:   ensemble voting runs
Then:   no majority exists
        session.session_type = 'mixed' (safe default)
        session.classification_confidence = 0.0
        session is flagged for operator review
        a notification event is published
```

#### T35.5 — Misclassification is correctable post hoc and triggers re-routing
```
Given:  a session initially classified as 'content' (all segments routed to db_2)
When:   operator corrects to 'syllabus' via PATCH endpoint
Then:   session.session_type updated to 'syllabus'
        session.classification_method = 'operator_override'
        all segments re-routed: route_target updated to 'db_3'
        session.rerouted event published with segments_moved = N
        downstream note generation (S40+) uses new routing
```

### 8. Observability

| Type | Name | Description |
|---|---|---|
| Metric | `lis.classifier.session_total` | Counter of sessions classified by type |
| Metric | `lis.classifier.confidence` | Histogram of classification confidence scores |
| Metric | `lis.classifier.vote_disagreements_total` | Counter of ensemble disagreements |
| Metric | `lis.classifier.operator_overrides_total` | Counter of operator overrides |
| Metric | `lis.classifier.re_routing_total` | Counter of post-hoc re-routing events |
| Metric | `lis.classifier.segment_routes` | Counter of segments routed by target (db_2/db_3) |
| Span | `session_classification` | OpenTelemetry span covering full classification |
| Span | `segment_routing` | OpenTelemetry span covering per-segment routing |
| Span | `classification_llm_call` | Child span for the LLM classification call |
| Log | `classification_disagreement` | Warning when ensemble has no majority |
| Log | `classification_fallback` | Warning when LLM fails, rule-only classification used |
| Log | `operator_override_applied` | Info when operator override is applied |
| Log | `re_routing_completed` | Info after successful re-routing |

### 9. Rollback

- **Migration down:** Drop `sessions.classification_confidence`, `sessions.classification_method`, `sessions.classification_details`, `segments.route_target` columns.
- **Code revert:** Remove `src/ml/session_classifier.py`, `src/api/routes/sessions.py` PATCH endpoint additions.
- **Feature flag:** `FEATURE_SESSION_CLASSIFICATION` (env var) — when `false`, skip ensemble classification. Sessions keep their `session_type` from creation (operator-set or default `"content"`). Segments are not individually routed.
- **Data cleanup:** Set `segments.route_target = NULL`, `sessions.classification_* = NULL` for affected rows.

### 10. Exit Checklist

- [ ] Ensemble classifier implemented (LLM + 2 rule-based)
- [ ] Operator override at creation and post-hoc PATCH endpoint
- [ ] Per-segment routing for mixed sessions
- [ ] T35.1 through T35.5 all pass
- [ ] Classification accuracy > 0.90 on labelled sessions
- [ ] Misclassification correction triggers re-routing
- [ ] Observability metrics/spans wired
- [ ] Feature flags documented
- [ ] **Signed off:** ___________  Date: ___________

---

## Cross-cutting Concerns

### File Manifest — New Files to Create

| File | Stage | Purpose |
|---|---|---|
| `config/greeting_keywords.yaml` | S33 | Configurable greeting keyword patterns |
| `config/transition_cues.yaml` | S34 | Transition cue patterns and weights |
| `src/ml/__init__.py` | — | Package init (if not exists) |
| `src/ml/greeting.py` | S33 | Greeting keyword detector |
| `src/ml/provisional_window.py` | S33 | Provisional topic window pass |
| `src/ml/transition_cues.py` | S34 | Transition cue detection + LLM confirmation |
| `src/ml/session_classifier.py` | S35 | Ensemble session type classifier |
| `src/ml/segment_router.py` | S35 | Per-segment routing logic |
| `tests/ml/test_greeting.py` | S33 | Greeting detection tests |
| `tests/ml/test_provisional_window.py` | S33 | Provisional window tests |
| `tests/ml/test_transition_cues.py` | S34 | Cue detection tests |
| `tests/ml/test_session_classifier.py` | S35 | Classification tests |
| `tests/ml/test_segment_router.py` | S35 | Routing tests |

### Files to Modify

| File | Stage | Changes |
|---|---|---|
| `src/db/models/session.py` | S35 | Add `classification_confidence`, `classification_method`, `classification_details` columns |
| `src/db/models/segment.py` | S34, S35 | Add `cue_metadata` (JSONB), `route_target` (VARCHAR) columns |
| `src/db/repositories/session_repo.py` | S35 | Add `update_session_type()` method |
| `src/api/schemas/session.py` | S35 | Add `ClassificationOverride` schema, update `SessionResponse` |
| `src/api/routes/sessions.py` | S35 | Add `PATCH /sessions/{session_id}/classification` endpoint |
| `src/core/config.py` | All | Add config keys for greeting, cues, classifier |
| `config/models.yaml` | — | No changes (existing models sufficient) |

### Migration Order

```
1. Create Alembic migration for:
   - topics.provisional (BOOLEAN, DEFAULT TRUE)
   - segments.cue_metadata (JSONB, DEFAULT NULL)
   - segments.route_target (VARCHAR(20), DEFAULT NULL)
   - sessions.classification_confidence (FLOAT, DEFAULT NULL)
   - sessions.classification_method (VARCHAR(20), DEFAULT NULL)
   - sessions.classification_details (JSONB, DEFAULT NULL)

2. Migration revision depends_on: c58ea6212bc5 (S09+S10 migration)
```

### Implementation Sequence

```
S33 → S34 → S35 (sequential within Block 5)
S33 depends on S30 (complete)
S34 depends on S28, S31 (complete)
S35 depends on S34 (within block), S36 (Block 6, must start in parallel)
```

### Open Questions

1. **S35 estimate:** Needs S36 (LLM serving) to be stable before ensemble classification can be fully tested. Should S35 be estimated with a dependency on S36 completion?
2. **Provisional topic persistence:** Should provisional topics live in the same `topics` table with a flag, or in a separate `topics_provisional` table? The current spec uses a flag — may need migration adjustment if the table grows large.
3. **Transition cue pattern validation:** The S05 corpus (30 hand-marked lectures) must be annotated with transition cue ground truth before T34.2 can be evaluated. Is this annotation part of S05 or a new sub-task?
4. **Mixed session routing edge case:** What happens when a mixed session has a very short syllabus segment (e.g., 30 seconds)? Should there be a minimum segment length threshold before routing to DB-3?
5. **Ensemble disagreement flagging:** How is the "flag for review" notification delivered? Email? Dashboard alert? Valkey stream consumer? Needs clarification for T35.4.

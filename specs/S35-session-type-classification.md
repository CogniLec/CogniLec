# S35 — Session Type Classification & Routing
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Classify each session as `content` / `syllabus` / `mixed` from its transcript using ensemble voting (cheap, high-consequence decision per v2.0 §4.1) with an operator override at session start. For `mixed` sessions, route segments individually — a first lecture covering syllabus then teaching is the common case, not an exception.

**Component Boundaries:**
- **Allowed:** `src/ml/session_classifier/`, `src/services/session_classifier.py`, `src/services/segment_router.py`, `tests/test_session_classifier.py`, `tests/test_segment_router.py`, `config/classifier_config.yaml`
- **Off-limits:** Segmentation (S28), clustering (S30), greeting detection (S33), transition cues (S34), LLM serving (S36)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| LLM (local vLLM) | 0.5.x | Ensemble member — LLM-based classifier |
| scikit-learn | 1.5.1 | Ensemble member — ML-based classifier |
| regex | 2024.x | Ensemble member — rule-based classifier |
| pydantic | 2.x | Config and result models |
| pytest | 8.x | Unit and integration tests |

---

### 2. State Machine & Domain Schemas

**Session Classification Pipeline:**
```
Input: session transcript with utterances + session metadata
  ↓
Check for operator override (set at session start)
  ↓
If no override:
  ├── Rule-based classifier (fast, deterministic)
  ├── ML-based classifier (trained on labelled sessions)
  ├── LLM-based classifier (contextual understanding)
  ↓
Ensemble voting:
  ├── Unanimous agreement → use agreed type
  ├── 2/3 majority → use majority type (log disagreement)
  ├── No majority → flag for human review
  ↓
Set session_type on sessions table
  ↓
For "mixed" sessions: route segments individually
  ↓
Output: ClassificationResult (type, confidence, method, segments_routed)
```

**Segment-Level Routing (for `mixed` sessions):**
```
Input: mixed session with segments from S28
  ↓
For each segment:
  ├── Classify segment as "content" or "syllabus"
  │   ├── Rule-based: keywords, structure patterns
  │   ├── LLM-based: contextual understanding of segment content
  │   └── Ensemble vote per segment
  ↓
Route "syllabus" segments → DB-3 (PG-SYLLABUS)
Route "content" segments → DB-2 (notes)
  ↓
Output: SegmentRoutingResult (segment_id, type, target_db)
```

**Pydantic Models:**
```python
# src/ml/session_classifier/models.py
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime


class SessionType(str, Enum):
    CONTENT = "content"
    SYLLABUS = "syllabus"
    MIXED = "mixed"


class SegmentType(str, Enum):
    CONTENT = "content"
    SYLLABUS = "syllabus"


class ClassifierMethod(str, Enum):
    RULE_BASED = "rule_based"
    ML_BASED = "ml_based"
    LLM_BASED = "llm_based"
    ENSEMBLE = "ensemble"
    OPERATOR_OVERRIDE = "operator_override"


class ClassifierConfig(BaseModel):
    ensemble_weights: dict[ClassifierMethod, float] = Field(
        default={
            ClassifierMethod.RULE_BASED: 0.2,
            ClassifierMethod.ML_BASED: 0.4,
            ClassifierMethod.LLM_BASED: 0.4,
        }
    )
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    review_threshold: float = Field(
        default=0.4, ge=0.0, le=1.0, description="Below this → flag for review"
    )
    llm_model: str = "phi-3-mini-3.8b-4bit"
    ml_model_path: str = "models/session_classifier.joblib"
    min_segments_for_mixed: int = Field(
        default=3, ge=2, description="Minimum segments to consider mixed"
    )


class ClassificationResult(BaseModel):
    session_id: str
    session_type: SessionType
    confidence: float
    method: ClassifierMethod
    ensemble_votes: dict[SessionType, float] = Field(default_factory=dict)
    review_flagged: bool = False
    classified_at: datetime = Field(default_factory=datetime.utcnow)
    operator_override: bool = False


class SegmentClassification(BaseModel):
    segment_id: str
    segment_type: SegmentType
    confidence: float
    method: ClassifierMethod
    target_db: str  # "db-2" or "db-3"


class SegmentRoutingResult(BaseModel):
    session_id: str
    session_type: SessionType
    segments_routed: list[SegmentClassification]
    db2_segments: int
    db3_segments: int
    total_segments: int


class OperatorOverride(BaseModel):
    session_id: str
    session_type: SessionType
    operator_id: str
    reason: str | None = None
    applied_at: datetime = Field(default_factory=datetime.utcnow)
```

**Ensemble Voting Logic:**
```
For each classifier, get vote (SessionType) + confidence:
  rule_based: keyword/structure patterns → SessionType
  ml_based: trained classifier on session features → SessionType
  llm_based: LLM reads transcript summary → SessionType

Weighted vote:
  total_score[type] = sum(weight[classifier] * confidence[classifier]
                          for classifier that voted for type)

Decision:
  if max(total_score) / sum(total_score) > 0.6:
    → unanimous or strong majority → use winning type
  elif max(total_score) / sum(total_score) > 0.4:
    → partial majority → use winning type, log disagreement
  else:
    → no majority → flag for human review
```

**Segment Routing Logic (mixed sessions):**
```
For each segment in mixed session:
  1. Extract segment utterances
  2. Classify segment type (content vs syllabus):
     - Rule-based: look for syllabus keywords (outline, objectives, assessment, schedule)
     - LLM-based: ask LLM "Is this segment about course structure or about content?"
     - Ensemble vote per segment
  3. Route based on type:
     - syllabus → DB-3 via SyllabusRepository (S50/S11)
     - content → DB-2 via NoteRepository (S45/S10)
  4. Persist routing decision on segment
```

**State Transition Rules:**
- Classification runs after session is `transcribed`
- Operator override is set at session start (before transcription)
- Override takes precedence over all classifiers
- Mixed sessions route segments individually; the session_type is `mixed`, not split into multiple sessions
- Misclassification is correctable post hoc: reclassify → re-route affected segments
- Ensemble disagreement flags session for review; processing continues with provisional type

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `config/classifier_config.yaml` with ensemble weights and thresholds | YAML loads without error |
| 2 | Implement rule-based classifier with keyword/structure patterns | Deterministic classification on known patterns |
| 3 | Implement ML-based classifier with scikit-learn model | Model loads and classifies sessions |
| 4 | Implement LLM-based classifier with prompt template | LLM returns classification with confidence |
| 5 | Implement ensemble voting with weighted scores | T35.1, T35.4 pass |
| 6 | Implement operator override mechanism | T35.3 passes |
| 7 | Implement segment-level classifier for mixed sessions | T35.2 passes |
| 8 | Implement segment routing to DB-2/DB-3 | T35.2 passes |
| 9 | Implement misclassification correction and re-routing | T35.5 passes |
| 10 | Run accuracy evaluation on labelled sessions | T35.1 passes |

**Atomic Sub-tasks:**
1. Rule-based classifier (keyword/structure patterns)
2. ML-based classifier (scikit-learn trained model)
3. LLM-based classifier (prompt + local LLM)
4. Ensemble voting with weighted scores
5. Operator override at session start
6. Segment-level classifier for mixed sessions
7. Segment routing to DB-2/DB-3
8. Misclassification correction and re-routing
9. Accuracy evaluation on labelled sessions

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| All classifiers disagree | Flag for human review, use provisional type |
| LLM classifier unavailable | Fall back to rule + ML ensemble only |
| ML model file missing | Fall back to rule + LLM ensemble |
| Operator override conflict | Override always wins; log conflict |
| Mixed session with 1 segment | Treat as content (not enough segments for mixed routing) |
| Segment classification confidence low | Use majority vote, log low confidence |
| DB-3 unavailable during routing | Queue segment for retry, continue with DB-2 segments |
| Misclassification discovered post-hoc | Reclassify session, re-route affected segments |
| Session has no clear type indicators | Flag for review, use content as default |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: pluggable classifiers (rule, ML, LLM)
- Ensemble pattern: weighted voting across classifiers
- Strategy pattern: pluggable routing strategies per segment type
- Guard pattern: operator override takes precedence
- Repository pattern: `SyllabusRepository` (DB-3), `NoteRepository` (DB-2)

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`rule_classifier.py`, `segment_router.py`)
- Constants: UPPER_SNAKE_CASE
- Config keys: lowercase with underscores

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Session Classifier Interface:**
```python
# src/ml/session_classifier/classifier.py
class SessionClassifier:
    def __init__(self, config: ClassifierConfig):
        self.config = config
        self.rule_classifier = RuleBasedClassifier()
        self.ml_classifier = MLBasedClassifier(config.ml_model_path)
        self.llm_classifier = LLMBasedClassifier(config.llm_model)

    async def classify(
        self,
        session_id: str,
        utterances: list[str],
        operator_override: OperatorOverride | None = None,
    ) -> ClassificationResult:
        """
        Classify session type using ensemble voting.
        Operator override takes precedence over all classifiers.
        """
        # Check operator override first
        if operator_override:
            return ClassificationResult(
                session_id=session_id,
                session_type=operator_override.session_type,
                confidence=1.0,
                method=ClassifierMethod.OPERATOR_OVERRIDE,
                operator_override=True,
            )

        # Run all classifiers
        rule_vote = self.rule_classifier.classify(utterances)
        ml_vote = await self.ml_classifier.classify(utterances)
        llm_vote = await self.llm_classifier.classify(utterances)

        # Ensemble voting
        votes = {
            ClassifierMethod.RULE_BASED: rule_vote,
            ClassifierMethod.ML_BASED: ml_vote,
            ClassifierMethod.LLM_BASED: llm_vote,
        }

        return self._ensemble_vote(session_id, votes)

    def _ensemble_vote(
        self, session_id: str, votes: dict[ClassifierMethod, tuple[SessionType, float]]
    ) -> ClassificationResult:
        """Weighted ensemble voting."""
        scores: dict[SessionType, float] = {t: 0.0 for t in SessionType}
        total_weight = sum(self.config.ensemble_weights.values())

        for method, (stype, confidence) in votes.items():
            weight = self.config.ensemble_weights[method]
            scores[stype] += weight * confidence

        # Normalize scores
        max_score = max(scores.values())
        total_score = sum(scores.values())
        normalized = {t: s / total_score for t, s in scores.items()}

        winning_type = max(scores, key=scores.get)
        winning_ratio = normalized[winning_type]

        if winning_ratio >= self.config.confidence_threshold:
            return ClassificationResult(
                session_id=session_id,
                session_type=winning_type,
                confidence=winning_ratio,
                method=ClassifierMethod.ENSEMBLE,
                ensemble_votes=normalized,
            )
        elif winning_ratio >= self.config.review_threshold:
            return ClassificationResult(
                session_id=session_id,
                session_type=winning_type,
                confidence=winning_ratio,
                method=ClassifierMethod.ENSEMBLE,
                ensemble_votes=normalized,
                review_flagged=True,
            )
        else:
            # No majority — flag for review
            return ClassificationResult(
                session_id=session_id,
                session_type=winning_type,  # Provisional
                confidence=winning_ratio,
                method=ClassifierMethod.ENSEMBLE,
                ensemble_votes=normalized,
                review_flagged=True,
            )
```

**Rule-Based Classifier Interface:**
```python
# src/ml/session_classifier/rule_classifier.py
class RuleBasedClassifier:
    SYLLABUS_KEYWORDS = [
        "syllabus",
        "outline",
        "objectives",
        "learning outcomes",
        "assessment",
        "grading",
        "schedule",
        "prerequisites",
        "course structure",
        "module",
        "unit",
        "week",
        "assignment",
        "exam",
        "quiz",
        "project",
        "required reading",
        "textbook",
        "references",
    ]

    CONTENT_KEYWORDS = [
        "let's dive into",
        "the theory is",
        "proof of",
        "example",
        "demonstration",
        "derivation",
        "first, we'll",
        "now consider",
        "recall that",
        "in practice",
        "the key insight",
        "algorithm",
    ]

    def classify(self, utterances: list[str]) -> tuple[SessionType, float]:
        """Classify using keyword density and structure patterns."""
        text = " ".join(utterances).lower()

        syllabus_score = sum(1 for kw in self.SYLLABUS_KEYWORDS if kw in text)
        content_score = sum(1 for kw in self.CONTENT_KEYWORDS if kw in text)

        total = syllabus_score + content_score
        if total == 0:
            return SessionType.CONTENT, 0.5  # Default to content

        syllabus_ratio = syllabus_score / total
        content_ratio = content_score / total

        if syllabus_ratio > 0.6:
            return SessionType.SYLLABUS, syllabus_ratio
        elif content_ratio > 0.6:
            return SessionType.CONTENT, content_ratio
        else:
            return SessionType.MIXED, max(syllabus_ratio, content_ratio)
```

**LLM-Based Classifier Interface:**
```python
# src/ml/session_classifier/llm_classifier.py
class LLMBasedClassifier:
    CLASSIFICATION_PROMPT = """Classify this lecture transcript as one of:
- content: Teaching substantive material (concepts, proofs, examples)
- syllabus: Course logistics (outline, objectives, assessment, schedule)
- mixed: Contains significant portions of both

Transcript summary:
{summary}

Respond with:
TYPE: <content|syllabus|mixed>
CONFIDENCE: <0.0-1.0>
REASON: <brief explanation>"""

    async def classify(
        self, utterances: list[str], model: str = "phi-3-mini-3.8b-4bit"
    ) -> tuple[SessionType, float]:
        """Classify session using LLM with transcript summary."""
        summary = self._create_summary(utterances)
        prompt = self.CLASSIFICATION_PROMPT.format(summary=summary)

        response = await self.llm_client.complete(prompt, model=model)
        return self._parse_response(response)

    def _create_summary(self, utterances: list[str], max_utterances: int = 50) -> str:
        """Create a condensed summary for LLM classification."""
        # Sample first, middle, and last utterances
        if len(utterances) <= max_utterances:
            return "\n".join(utterances)

        sampled = []
        sampled.extend(utterances[:15])  # First 15
        mid = len(utterances) // 2
        sampled.extend(utterances[mid - 10 : mid + 10])  # Middle 20
        sampled.extend(utterances[-15:])  # Last 15
        return "\n".join(sampled)
```

**Segment Router Interface:**
```python
# src/services/segment_router.py
class SegmentRouter:
    def __init__(self, config: ClassifierConfig):
        self.config = config
        self.segment_classifier = SegmentClassifier()

    async def route_segments(
        self,
        session_id: str,
        session_type: SessionType,
        segments: list[dict],  # From S28
    ) -> SegmentRoutingResult:
        """
        For mixed sessions, route each segment individually.
        For content/syllabus, route all segments to appropriate DB.
        """
        if session_type == SessionType.CONTENT:
            return self._route_all(segments, SegmentType.CONTENT, "db-2")
        elif session_type == SessionType.SYLLABUS:
            return self._route_all(segments, SegmentType.SYLLABUS, "db-3")
        else:
            # MIXED — route each segment individually
            return await self._route_mixed(session_id, segments)

    async def _route_mixed(self, session_id: str, segments: list[dict]) -> SegmentRoutingResult:
        """Route each segment in a mixed session individually."""
        routed = []
        for seg in segments:
            seg_type = await self.segment_classifier.classify_segment(seg["utterances"])
            target = "db-3" if seg_type == SegmentType.SYLLABUS else "db-2"
            routed.append(
                SegmentClassification(
                    segment_id=seg["id"],
                    segment_type=seg_type,
                    confidence=seg_type.confidence,
                    method=seg_type.method,
                    target_db=target,
                )
            )

            # Write to appropriate DB
            if target == "db-3":
                await self._write_to_db3(session_id, seg)
            else:
                await self._write_to_db2(session_id, seg)

        return SegmentRoutingResult(
            session_id=session_id,
            session_type=SessionType.MIXED,
            segments_routed=routed,
            db2_segments=sum(1 for r in routed if r.target_db == "db-2"),
            db3_segments=sum(1 for r in routed if r.target_db == "db-3"),
            total_segments=len(routed),
        )

    def _route_all(
        self, segments: list[dict], seg_type: SegmentType, target: str
    ) -> SegmentRoutingResult:
        """Route all segments to one DB (non-mixed sessions)."""
        routed = [
            SegmentClassification(
                segment_id=seg["id"],
                segment_type=seg_type,
                confidence=1.0,
                method=ClassifierMethod.ENSEMBLE,
                target_db=target,
            )
            for seg in segments
        ]
        return SegmentRoutingResult(
            session_id="",  # Set by caller
            session_type=SessionType.CONTENT if target == "db-2" else SessionType.SYLLABUS,
            segments_routed=routed,
            db2_segments=len(routed) if target == "db-2" else 0,
            db3_segments=len(routed) if target == "db-3" else 0,
            total_segments=len(routed),
        )
```

**Segment Classifier Interface:**
```python
# src/ml/session_classifier/segment_classifier.py
class SegmentClassifier:
    SYLLABUS_PATTERNS = [
        r"\b(outline|objectives?|learning outcomes?|assessment|grading)\b",
        r"\b(schedule|syllabus|prerequisites?|module|unit)\b",
        r"\b(assignment|exam|quiz|project|required reading)\b",
        r"\b(week \d+|chapter \d+|unit \d+)\b",
    ]

    async def classify_segment(self, utterances: list[str]) -> SegmentClassification:
        """Classify a single segment as content or syllabus."""
        text = " ".join(utterances).lower()

        # Rule-based check
        syllabus_matches = sum(1 for p in self.SYLLABUS_PATTERNS if re.search(p, text))
        if syllabus_matches >= 2:
            return SegmentClassification(
                segment_id="",
                segment_type=SegmentType.SYLLABUS,
                confidence=0.8,
                method=ClassifierMethod.RULE_BASED,
                target_db="db-3",
            )

        # LLM check for ambiguous cases
        llm_result = await self._llm_classify_segment(utterances)
        return llm_result
```

**Operator Override Endpoint:**
```yaml
POST /api/v1/sessions/{session_id}/override-type
Content-Type: application/json

Request:
{
  "session_type": "mixed",
  "operator_id": "admin-001",
  "reason": "Lecturer started with syllabus overview then moved to teaching"
}

Response: 201 Created
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_type": "mixed",
  "operator_override": true,
  "applied_at": "2026-09-12T10:00:00Z"
}
```

**Classification Result Endpoint:**
```yaml
GET /api/v1/sessions/{session_id}/classification
Response: 200 OK
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_type": "mixed",
  "confidence": 0.85,
  "method": "ensemble",
  "ensemble_votes": {
    "content": 0.15,
    "syllabus": 0.35,
    "mixed": 0.50
  },
  "review_flagged": false,
  "classified_at": "2026-09-12T10:05:00Z",
  "operator_override": false,
  "segment_routing": {
    "total_segments": 5,
    "db2_segments": 3,
    "db3_segments": 2
  }
}
```

**Re-classification Endpoint (post-hoc correction):**
```yaml
POST /api/v1/sessions/{session_id}/reclassify
Content-Type: application/json

Request:
{
  "session_type": "content",
  "reason": "Operator determined all segments are content, not syllabus"
}

Response: 200 OK
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_type": "content",
  "reclassified": true,
  "segments_re_routed": 2,
  "reclassified_at": "2026-09-12T11:00:00Z"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `CLASSIFIER_ENSEMBLE_WEIGHTS` | string | JSON of classifier weights | `{"rule_based":0.2,"ml_based":0.4,"llm_based":0.4}` |
| `CLASSIFIER_CONFIDENCE_THRESHOLD` | float | Minimum confidence for definitive classification | `0.6` |
| `CLASSIFIER_REVIEW_THRESHOLD` | float | Below this → flag for review | `0.4` |
| `CLASSIFIER_LLM_MODEL` | string | Model for LLM classifier | `phi-3-mini-3.8b-4bit` |
| `CLASSIFIER_ML_MODEL_PATH` | string | Path to trained ML model | `models/session_classifier.joblib` |
| `CLASSIFIER_MIN_SEGMENTS_MIXED` | int | Minimum segments for mixed classification | `3` |

**Third-Party Integration Contracts:**
- S28 Boundary Detection: provides segments for routing
- S36 Local LLM Serving: LLM classifier uses Tier 1 model
- S10 DB-2 (Notes): content segments route here
- S11 DB-3 (Syllabus): syllabus segments route here
- S50 A6 Syllabus Extraction: DB-3 write authority

**Version Pins:**
- scikit-learn >= 1.5.1 (ML classifier)
- joblib >= 1.3 (model serialization)

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T35.1 | V | `pytest tests/test_session_classifier.py::test_classification_accuracy -v` | Classification accuracy > 0.90 on labelled sessions |
| T35.2 | I | `pytest tests/test_segment_router.py::test_mixed_session_routing -v` | Mixed session routes syllabus segments to DB-3 and content to DB-2 |
| T35.3 | I | `pytest tests/test_session_classifier.py::test_operator_override -v` | Operator override takes precedence over classification |
| T35.4 | I | `pytest tests/test_session_classifier.py::test_ensemble_disagreement -v` | Ensemble disagreement flags session for review |
| T35.5 | I | `pytest tests/test_segment_router.py::test_misclassification_correction -v` | Misclassification is correctable post-hoc and triggers re-routing |

**Test Case Details (Given/When/Then):**

**T35.1 — Classification accuracy > 0.90**
- **Given:** 50 labelled sessions (20 content, 15 syllabus, 15 mixed) from S05 corpus
- **When:** ensemble classification is run on each session
- **Then:** accuracy > 0.90 (correct type predicted for > 90% of sessions); precision and recall reported per type

**T35.2 — Mixed session routes segments individually (FR-2.21)**
- **Given:** a session classified as `mixed` with 5 segments: 2 syllabus (course outline, grading) + 3 content (proofs, examples, derivation)
- **When:** segment routing runs on the mixed session
- **Then:** the 2 syllabus segments are routed to DB-3 (PG-SYLLABUS), the 3 content segments are routed to DB-2 (notes), and both sets are accessible from the session

**T35.3 — Operator override takes precedence**
- **Given:** a session classified as `content` by the ensemble
- **When:** an operator sets an override to `syllabus` at session start
- **Then:** the session type is `syllabus`, the override flag is set, and downstream processing uses `syllabus` routing (all segments → DB-3)

**T35.4 — Ensemble disagreement flags for review**
- **Given:** a session where rule-based votes `content` (0.7 confidence), ML votes `mixed` (0.5 confidence), LLM votes `syllabus` (0.6 confidence)
- **When:** ensemble voting runs
- **Then:** no classifier has > 60% weighted vote, the session is flagged for review (`review_flagged=true`), and processing continues with the provisional winning type

**T35.5 — Misclassification correctable post-hoc**
- **Given:** a session initially classified as `content` but later determined to be `mixed`
- **When:** operator triggers re-classification with corrected type
- **Then:** session type is updated, affected segments are re-routed (syllabus segments moved from DB-2 to DB-3), and a `re-routed` event is emitted

**Verification Commands:**
```bash
uv run pytest tests/test_session_classifier.py tests/test_segment_router.py -v -k "S35" && \
uv run mypy --strict src/ml/session_classifier/ src/services/segment_router.py && \
uv run ruff check src/ml/session_classifier/ src/services/segment_router.py
```

**Exit Criteria:**
- [ ] T35.1 passes — classification accuracy > 0.90 on labelled sessions
- [ ] T35.2 passes — mixed session routes segments individually to DB-2/DB-3 (FR-2.21)
- [ ] T35.3 passes — operator override takes precedence over classification
- [ ] T35.4 passes — ensemble disagreement flags session for review
- [ ] T35.5 passes — misclassification correctable post-hoc, triggers re-routing
- [ ] Session type determined reliably
- [ ] Mixed sessions handled without losing either half

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- **Mixed sessions are common, not exceptional** — a first lecture covering syllabus then teaching is the normal case; the classifier must handle this gracefully
- Segment-level routing for mixed sessions must be atomic — if DB-3 write fails but DB-2 succeeds, the session is in an inconsistent state
- Ensemble voting can produce ties — the `review_flagged` mechanism handles this; do not guess
- LLM classifier may be slow for long transcripts — use summary sampling (first/middle/last utterances)
- ML model requires labelled training data; cold-start sessions will have lower accuracy
- Operator override at session start must be captured before transcription begins; late overrides are rejected
- Re-routing after misclassification must handle DB-2 → DB-3 and DB-3 → DB-2 migrations cleanly

**Fallback Instructions:**
- If LLM classifier unavailable: use rule + ML ensemble only, log warning
- If ML model missing: use rule + LLM ensemble only
- If DB-3 unavailable: queue syllabus segments for retry, continue with content segments in DB-2
- If ensemble confidence < review_threshold: flag for review, use provisional type, do not block processing
- If re-routing fails: log error, leave segments in original DB, alert for manual intervention

**Rollback Procedure:**
- Disable ensemble: set individual classifier weights to 0 in env
- Revert to rule-only: set `CLASSIFIER_ENSEMBLE_WEIGHTS={"rule_based":1.0}`
- Revert operator override: remove override from session record (POST /api/v1/sessions/{id}/remove-override)
- Re-route segments: POST /api/v1/sessions/{id}/reclassify with correct type
- No schema migration rollback — classification is a field update on `sessions` table

---

### 9. Observability (if applicable)

**Metrics Added:**
- `session_classification_total`: counter of classifications (labels: type, method)
- `session_classification_confidence`: histogram of classification confidence scores
- `session_classification_review_flagged_total`: counter of sessions flagged for review
- `session_classification_override_total`: counter of operator overrides
- `session_classification_accuracy`: gauge of accuracy on evaluation set
- `segment_routing_total`: counter of segments routed (labels: target_db=db2/db3, session_type)
- `segment_routing_duration_seconds`: histogram of routing time per session
- `segment_reclassification_total`: counter of post-hoc reclassifications

**Tracing/Logging:**
- Span: `session_classifier.classify` with attributes (session_id, method, type, confidence, review_flagged)
- Span: `segment_router.route_segments` with attributes (session_id, session_type, total_segments, db2_count, db3_count)
- Span: `segment_classifier.classify_segment` with attributes (segment_id, type, confidence)
- Log: INFO on classification completion with type, confidence, method
- Log: INFO on ensemble voting with all classifier votes and weights
- Log: WARN on ensemble disagreement and review flagging
- Log: INFO on operator override application
- Log: INFO on segment routing with target DB per segment
- Log: INFO on reclassification with old → new type

**Alerts:**
- Classification accuracy < 0.85: model retraining needed
- Review flag rate > 30%: ensemble weights may need tuning
- Segment routing failures > 5%: DB availability issue
- Re-routing failures: manual intervention required

---

### 10. Exit Checklist

- [ ] All tests pass (T35.1, T35.2, T35.3, T35.4, T35.5)
- [ ] Classification accuracy > 0.90 on labelled sessions
- [ ] Mixed sessions route segments individually to DB-2 and DB-3 (FR-2.21)
- [ ] Operator override takes precedence over all classifiers
- [ ] Ensemble disagreement flags session for review (no guessing)
- [ ] Misclassification correctable post-hoc with re-routing
- [ ] All three session types (content, syllabus, mixed) handled correctly
- [ ] Segment-level routing for mixed sessions is atomic
- [ ] Re-routing after misclassification works for both DB-2→DB-3 and DB-3→DB-2

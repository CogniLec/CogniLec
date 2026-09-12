# S33 — Greeting Keywords & Topic Window
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Detect configurable greeting keywords as a session-start/boundary signal — never to classify or exclude a speaker — and run a provisional clustering pass over the first 10 minutes to establish early topic candidates surfaced to the client. The post-session full-transcript pass (S30) remains authoritative per FR-2.9.

**Component Boundaries:**
- **Allowed:** `src/ml/greeting/`, `src/services/greeting.py`, `src/services/provisional_topic.py`, `tests/test_greeting.py`, `tests/test_provisional_topic.py`, `config/greeting_keywords.yaml`
- **Off-limits:** Speaker diarisation/tagging (S21), relevance filtering (S41), segmentation (S28), clustering (S30), session type classification (S35)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| regex | 2024.x | Configurable keyword matching with Unicode support |
| pydantic | 2.x | Config and result models |
| pytest | 8.x | Unit and integration tests |
| hypothesis | 6.x | Property-based testing for greeting invariants |

---

### 2. State Machine & Domain Schemas

**Greeting Detection Pipeline:**
```
Input: session transcript with utterances + timestamps
  ↓
Scan first N utterances (configurable, default 5) for greeting keywords
  ↓
Match against configured keyword patterns (multi-language)
  ↓
Emit session_start_signal with confidence score
  ↓
  ⚠ EXPLICIT: greeting detection NEVER writes to speaker_tag or relevance fields
  ↓
Output: GreetingResult (detected: bool, confidence: float, keyword: str)
```

**Provisional Topic Window:**
```
Input: session transcript (first 10 minutes of utterances)
  ↓
Wait for 10-minute mark (streaming: accumulate until window closes)
  ↓
Run provisional clustering (lightweight subset of S30 pipeline)
  ↓
Surface provisional topics to client as "does this look like the right subject?"
  ↓
Output: ProvisionalTopicResult (topics: list, confidence: float, is_provisional: true)
```

**Pydantic Models:**
```python
# src/ml/greeting/models.py
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

class GreetingLanguage(str, Enum):
    EN = "en"
    ES = "es"
    FR = "fr"
    DE = "de"
    ZH = "zh"
    JA = "ja"
    HI = "hi"
    AR = "ar"
    PT = "pt"
    KO = "ko"

class GreetingKeyword(BaseModel):
    text: str
    language: GreetingLanguage
    variants: list[str] = Field(default_factory=list, description="Alternate phrasings")
    priority: int = Field(default=0, description="Higher = preferred match")

class GreetingConfig(BaseModel):
    languages: list[GreetingLanguage] = Field(default=[GreetingLanguage.EN])
    keywords_file: str = "config/greeting_keywords.yaml"
    scan_window_utterances: int = Field(default=5, ge=1, le=20, description="How many opening utterances to scan")
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    provisional_window_minutes: float = Field(default=10.0, ge=1.0, le=30.0)

class GreetingResult(BaseModel):
    detected: bool
    keyword_matched: str | None = None
    language: GreetingLanguage | None = None
    confidence: float = 0.0
    utterance_index: int | None = None  # Position of greeting utterance
    timestamp: datetime | None = None

class ProvisionalTopic(BaseModel):
    label: str | None = None
    keywords: list[str] = Field(default_factory=list)
    member_count: int
    is_provisional: bool = True

class ProvisionalTopicResult(BaseModel):
    session_id: str
    topics: list[ProvisionalTopic]
    total_utterances: int
    window_minutes: float
    is_final: bool = False  # Always False; S30 result is authoritative
    generated_at: datetime
```

**Session Start Signal (event):**
```json
{
  "event_type": "session.greeting_detected",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "subject_id": "550e8400-e29b-41d4-a716-446655440001",
  "detected": true,
  "keyword": "good morning",
  "language": "en",
  "confidence": 0.95,
  "utterance_index": 0,
  "timestamp": "2026-09-12T10:00:00Z"
}
```

**State Transition Rules:**
- Greeting detection runs on session `transcribed` status
- Provisional topic window runs after 10 minutes of accumulated utterances
- Provisional topics are advisory only; S30 full-clustering pass is authoritative
- If session < 10 minutes, provisional topic window completes with available data (no error)

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `config/greeting_keywords.yaml` with keyword definitions per language | YAML loads without error, all languages covered |
| 2 | Implement `GreetingDetector` class with keyword matching | Unit tests: greetings detected across phrasings |
| 3 | Implement explicit negative assertion: greeting detection never writes to `speaker_tag` or `relevance` | Integration test T33.2 passes |
| 4 | Implement `ProvisionalTopicService` using lightweight clustering | Provisional topics available within 60s of 10-minute mark |
| 5 | Wire greeting detection to session lifecycle (after ASR) | Detection fires on `session.transcribed` |
| 6 | Implement client-facing provisional topic feedback endpoint | Client receives topics within NFR-P2 |
| 7 | Verify short session (< 10 min) completes without error | T33.5 passes |
| 8 | Verify provisional vs final divergence on real sessions | T33.4 passes |

**Atomic Sub-tasks:**
1. Keyword configuration file and loader
2. Multi-language greeting pattern matching
3. Explicit negative assertion for speaker_tag/relevance (invariant)
4. Provisional topic window accumulator (10-minute sliding window)
5. Lightweight provisional clustering (UMAP + HDBSCAN subset)
6. Client-facing provisional topic feedback endpoint
7. Session lifecycle integration
8. Short session graceful handling

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| No greeting detected | Normal session start; no signal emitted |
| Greeting in unsupported language | Skip language-specific patterns; fall back to universal patterns |
| Session < 10 minutes | Complete provisional window with available data; mark as `is_final: false` |
| No utterances in first 5 positions | No greeting signal; session starts normally |
| Provisional clustering fails | Log error, return empty topic list; S30 still runs post-session |
| Greeting keyword matches mid-utterance | Only match at utterance start (word boundary) to avoid false positives |
| Multiple greetings detected | Use first match; confidence weighted by position (earlier = higher) |
| Provisional topics have 0 clusters | Return empty list; not an error — session may have single topic |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: pluggable greeting matchers per language
- Observer pattern: greeting detection emits events, does not mutate session state
- Pipeline pattern: sequential keyword scan → provisional clustering → feedback
- Guard pattern: explicit assertion preventing speaker_tag/relevance mutation

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`greeting_detector.py`, `provisional_topics.py`)
- Constants: UPPER_SNAKE_CASE
- Config keys: lowercase with underscores

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- No `Any` types; use `Union` or `Optional` with specific types

---

### 5. API & Interface Contracts

**Greeting Detection Interface:**
```python
# src/ml/greeting/detector.py
class GreetingDetector:
    def __init__(self, config: GreetingConfig):
        self.config = config
        self._patterns: dict[GreetingLanguage, list[re.Pattern]] = {}
        self._load_patterns()

    def detect(
        self,
        utterances: list[str],
        timestamps: list[datetime] | None = None,
    ) -> GreetingResult:
        """
        Scan first N utterances for greeting keywords.
        
        IMPORTANT: This method NEVER sets speaker_tag or relevance.
        It only returns a GreetingResult signal.
        """
        # Scan window (first N utterances)
        scan_limit = min(len(utterances), self.config.scan_window_utterances)
        
        for i in range(scan_limit):
            for lang, patterns in self._patterns.items():
                for pattern in patterns:
                    match = pattern.search(utterances[i].lower())
                    if match:
                        confidence = self._compute_confidence(
                            position=i, text=utterances[i], match=match
                        )
                        return GreetingResult(
                            detected=True,
                            keyword_matched=match.group(),
                            language=lang,
                            confidence=confidence,
                            utterance_index=i,
                            timestamp=timestamps[i] if timestamps else None,
                        )
        
        return GreetingResult(detected=False, confidence=0.0)
    
    def _compute_confidence(
        self, position: int, text: str, match: re.Match
    ) -> float:
        """Higher confidence for earlier positions and exact matches."""
        position_factor = 1.0 - (position / self.config.scan_window_utterances) * 0.3
        exact_factor = 1.0 if match.group() == text.strip().lower() else 0.8
        return min(1.0, position_factor * exact_factor)
```

**Provisional Topic Service Interface:**
```python
# src/services/provisional_topic.py
class ProvisionalTopicService:
    def __init__(self, config: GreetingConfig):
        self.config = config
        self._accumulated_utterances: dict[str, list[str]] = {}
        self._window_start: dict[str, datetime] = {}

    async def accumulate_utterance(
        self, session_id: str, utterance: str, timestamp: datetime
    ) -> ProvisionalTopicResult | None:
        """
        Accumulate utterances for provisional topic window.
        Returns ProvisionalTopicResult when window closes (10 min mark).
        Returns None if window still open.
        """
        if session_id not in self._accumulated_utterances:
            self._accumulated_utterances[session_id] = []
            self._window_start[session_id] = timestamp

        self._accumulated_utterances[session_id].append(utterance)
        
        elapsed = (timestamp - self._window_start[session_id]).total_seconds() / 60.0
        if elapsed >= self.config.provisional_window_minutes:
            return await self._compute_provisional_topics(session_id)
        
        return None

    async def _compute_provisional_topics(
        self, session_id: str
    ) -> ProvisionalTopicResult:
        """Lightweight clustering of accumulated utterances."""
        utterances = self._accumulated_utterances.pop(session_id, [])
        window_start = self._window_start.pop(session_id, None)
        
        # Use existing embedding + mini-clustering pipeline
        # (subset of S30, not full BERTopic)
        topics = await self._lightweight_cluster(utterances)
        
        return ProvisionalTopicResult(
            session_id=session_id,
            topics=topics,
            total_utterances=len(utterances),
            window_minutes=self.config.provisional_window_minutes,
            is_final=False,  # NEVER final — S30 is authoritative
            generated_at=datetime.utcnow(),
        )
```

**Keyword Configuration File:**
```yaml
# config/greeting_keywords.yaml
languages:
  - code: en
    keywords:
      - text: "good morning"
        variants: ["morning everyone", "good morning class", "good morning students"]
        priority: 1
      - text: "good afternoon"
        variants: ["afternoon everyone", "good afternoon class"]
        priority: 1
      - text: "good evening"
        variants: ["evening everyone"]
        priority: 1
      - text: "hello"
        variants: ["hello everyone", "hello class", "hi everyone", "hi class"]
        priority: 0
      - text: "welcome"
        variants: ["welcome back", "welcome to", "welcome everyone"]
        priority: 0
  - code: es
    keywords:
      - text: "buenos días"
        variants: ["buenos dias"]
        priority: 1
      - text: "buenas tardes"
        priority: 1
      - text: "hola"
        variants: ["hola a todos"]
        priority: 0
  - code: fr
    keywords:
      - text: "bonjour"
        variants: ["bonjour à tous"]
        priority: 1
      - text: "bonsoir"
        priority: 1
  - code: de
    keywords:
      - text: "guten morgen"
        priority: 1
      - text: "guten tag"
        priority: 1
      - text: "guten abend"
        priority: 1
  - code: zh
    keywords:
      - text: "大家好"
        priority: 1
      - text: "同学们好"
        priority: 1
  - code: ja
    keywords:
      - text: "みなさん おはよう"
        variants: ["皆さん おはようございます"]
        priority: 1
  - code: hi
    keywords:
      - text: "नमस्ते"
        priority: 1
      - text: "सुप्रभात"
        priority: 1
  - code: ar
    keywords:
      - text: "مرحبا"
        priority: 1
      - text: "صباح الخير"
        priority: 1
  - code: pt
    keywords:
      - text: "bom dia"
        priority: 1
      - text: "boa tarde"
        priority: 1
  - code: ko
    keywords:
      - text: "안녕하세요"
        priority: 1
```

**Client Feedback Endpoint:**
```yaml
GET /api/v1/sessions/{session_id}/provisional-topics
Response: 200 OK
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "topics": [
    {
      "label": "Cell Division",
      "keywords": ["mitosis", "chromosome", "cell cycle"],
      "member_count": 12,
      "is_provisional": true
    }
  ],
  "total_utterances": 45,
  "window_minutes": 10.0,
  "is_final": false,
  "generated_at": "2026-09-12T10:10:00Z"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `GREETING_LANGUAGES` | string | Comma-separated language codes | `en` |
| `GREETING_KEYWORDS_FILE` | string | Path to keywords YAML | `config/greeting_keywords.yaml` |
| `GREETING_SCAN_WINDOW` | int | Number of opening utterances to scan | `5` |
| `GREETING_CONFIDENCE_THRESHOLD` | float | Minimum confidence to emit signal | `0.7` |
| `PROVISIONAL_WINDOW_MINUTES` | float | Duration of provisional topic window | `10.0` |

**Third-Party Integration Contracts:**
- Embedding service (S25): provisional clustering needs embeddings for accumulated utterances
- Prefect (S27): session lifecycle triggers greeting detection after ASR
- Database (S07): session status and type fields (read-only for this stage)

**Version Pins:**
- regex >= 2024.0 (Unicode support for multi-language patterns)
- hypothesis >= 6.0 (property-based testing)

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T33.1 | U | `pytest tests/test_greeting.py::test_greeting_detected_across_phrases -v` | Greeting keywords detected across phrasings and configured languages |
| T33.2 | I | `pytest tests/test_greeting.py::test_greeting_never_sets_speaker_tag -v` | Greeting detection never sets or influences speaker_tag or relevance |
| T33.3 | I | `pytest tests/test_provisional_topic.py::test_provisional_within_60s -v` | Provisional topics available within 60s of the 10-minute mark (NFR-P2) |
| T33.4 | V | `pytest tests/test_provisional_topic.py::test_provisional_differs_from_final -v` | Provisional result differs from final on at least one real session; final is used |
| T33.5 | I | `pytest tests/test_provisional_topic.py::test_short_session_no_error -v` | Session shorter than 10 minutes completes without error |

**Test Case Details (Given/When/Then):**

**T33.1 — Greeting keywords detected across phrasings**
- **Given:** greeting keywords configured for English ("good morning", "hello", "welcome") with variants
- **When:** transcripts containing "Good morning everyone", "Hello class", "Welcome back students" are scanned
- **Then:** each transcript produces a `GreetingResult` with `detected=True`, correct `keyword_matched`, and `confidence > 0.7`

**T33.2 — Greeting detection never sets speaker_tag or relevance (EXPLICIT NEGATIVE ASSERTION)**
- **Given:** a session transcript with a greeting utterance at position 0
- **When:** greeting detection runs and completes
- **Then:** the `speaker_tag` field on all utterances remains unchanged from its pre-detection value (None or existing value), the `relevance` field on all utterances remains unchanged, and no database write targets either column

**T33.3 — Provisional topics within 60s of 10-minute mark**
- **Given:** a session with utterances spanning 10 minutes of content
- **When:** the 10-minute provisional window closes
- **Then:** a `ProvisionalTopicResult` is returned with at least one topic, generated within 60 seconds of the window close (NFR-P2)

**T33.4 — Provisional differs from final (proves FR-2.9 authority)**
- **Given:** a session with two distinct topics where the first 10 minutes suggest topic A, but the full session is dominated by topic B
- **When:** provisional clustering runs at 10 minutes, and full S30 clustering runs post-session
- **Then:** the provisional result differs from the final result on at least one topic label/assignment, and the final result is used for all downstream operations (notes, retrieval)

**T33.5 — Short session completes without error**
- **Given:** a session with only 3 minutes of content (below the 10-minute provisional window)
- **When:** the session completes and the provisional window timer fires
- **Then:** the system returns a `ProvisionalTopicResult` with available data (3 minutes worth), `is_final=false`, and no error is raised

**Verification Commands:**
```bash
uv run pytest tests/test_greeting.py tests/test_provisional_topic.py -v -k "S33" && \
uv run mypy --strict src/ml/greeting/ src/services/provisional_topic.py && \
uv run ruff check src/ml/greeting/ src/services/provisional_topic.py
```

**Exit Criteria:**
- [ ] T33.1 passes — greeting keywords detected across phrasings and languages
- [ ] T33.2 passes — greeting detection never sets speaker_tag or relevance
- [ ] T33.3 passes — provisional topics within 60s of 10-minute mark
- [ ] T33.4 passes — provisional differs from final; final is authoritative
- [ ] T33.5 passes — short session completes without error
- [ ] Early topic feedback delivered to client
- [ ] Post-session pass (S30) demonstrably authoritative

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- **CRITICAL: Greeting detection must NEVER write to `speaker_tag` or `relevance`** — this is an explicit negative assertion from the implementation plan; any regression here is a severity-1 bug
- Provisional clustering is lightweight — it will produce lower quality results than S30 full clustering by design; do not treat provisional results as final
- Unicode greeting patterns (Chinese, Japanese, Arabic) require Unicode-aware regex; `re.UNICODE` flag must be set
- Keyword matching at utterance start only — mid-utterance matches (e.g., "we said good morning to each other") are false positives
- Multiple greetings in first 5 utterances — use first match only; lecturer may greet, pause, greet again
- Provisional window accumulates utterances in memory; if session crashes before window closes, data is lost (acceptable — S30 re-runs post-session)

**Fallback Instructions:**
- If greeting detection fails: session starts normally, no signal emitted, processing continues
- If provisional clustering fails: return empty topic list, log error, S30 still runs post-session
- If keywords file is missing or malformed: fall back to built-in English defaults, log warning
- If provisional window exceeds 60s: investigate embedding service latency, alert if > 120s

**Rollback Procedure:**
- Disable greeting detection: set `GREETING_SCAN_WINDOW=0` in env (feature flag)
- Disable provisional topics: set `PROVISIONAL_WINDOW_MINUTES=9999` (effectively disables)
- No database schema changes to revert — greeting detection is stateless
- Provisional topics are ephemeral (in-memory); no persistence to roll back

---

### 9. Observability (if applicable)

**Metrics Added:**
- `greeting_detection_total`: counter of greeting detection runs (labels: language, detected=true/false)
- `greeting_confidence_histogram`: histogram of greeting confidence scores
- `greeting_keyword_match_total`: counter of keyword matches (labels: keyword, language)
- `provisional_topic_window_duration_seconds`: histogram of provisional window accumulation time
- `provisional_topic_count`: histogram of topics returned per provisional run
- `provisional_topic_utterance_count`: histogram of utterances in provisional window

**Tracing/Logging:**
- Span: `greeting.detect` with attributes (session_id, language, detected, confidence, utterance_index)
- Span: `provisional_topic.compute` with attributes (session_id, utterance_count, topic_count, window_minutes)
- Log: INFO on greeting detection with keyword and confidence
- Log: INFO on provisional topic computation with summary
- Log: WARN on provisional window exceeding 60s target
- Log: DEBUG on keyword pattern matching (per utterance)

**Alerts:**
- Provisional topic computation > 60s: investigate embedding service or clustering performance
- Greeting detection false positive rate > 10%: review keyword patterns, check for mid-utterance matches
- Provisional window memory usage > 100MB per session: check for accumulation leak

---

### 10. Exit Checklist

- [ ] All tests pass (T33.1, T33.2, T33.3, T33.4, T33.5)
- [ ] Greeting keywords detected across all configured languages and phrasings
- [ ] Greeting detection NEVER sets speaker_tag or relevance (explicit negative assertion verified)
- [ ] Provisional topics available within 60s of 10-minute mark (NFR-P2)
- [ ] Provisional result differs from final on at least one real session (FR-2.9 authority)
- [ ] Short sessions (< 10 min) complete without error
- [ ] Early topic feedback delivered to client
- [ ] Post-session S30 pass demonstrably authoritative
- [ ] Config file supports multi-language greetings

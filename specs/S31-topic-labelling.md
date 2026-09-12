# S31 — Topic Labelling & Keyword Extraction
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Apply c-TF-IDF + KeyBERT for side keywords per cluster, then use LLM to label each cluster from its top-N representative utterances plus keywords. Labels are human-editable and persisted to `topics`.

**Component Boundaries:**
- **Allowed:** `src/ml/labelling/`, `src/services/labelling.py`, `src/db/repositories/topic_repo.py`, `tests/test_labelling.py`
- **Off-limits:** Cross-session identity (S32), clustering (S30), A1 relevance (S41)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| KeyBERT | 0.8.x | Keyword extraction |
| c-TF-IDF | via BERTopic | Class-based TF-IDF |
| BERTopic | 0.16.x | Topic keyword extraction |
| LLM (local vLLM) | 0.5.x | Cluster labelling |
| pytest | 8.x | Tests |

---

### 2. State Machine & Domain Schemas

**Labelling Pipeline:**
```
Input: topics with centroids and member utterances
  ↓
Extract keywords via c-TF-IDF + KeyBERT
  ↓
Select top-N representative utterances per topic
  ↓
LLM labels each topic from utterances + keywords
  ↓
Persist labels and keywords to topics table
  ↓
User can edit labels via API (not overwritten by re-clustering)
```

**Pydantic Models:**
```python
# src/ml/labelling/models.py
from pydantic import BaseModel, Field

class LabellingConfig(BaseModel):
    top_n_utterances: int = Field(default=10, ge=3, le=50, description="Representative utterances for LLM")
    top_n_keywords: int = Field(default=10, ge=3, le=20, description="Keywords per topic")
    llm_model: str = "phi-3-mini-3.8b-4bit"
    llm_temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    max_label_length: int = Field(default=100, ge=10, le=200)

class TopicLabel(BaseModel):
    topic_id: UUID
    label: str
    keywords: list[str]
    representative_utterances: list[str]
    is_user_edited: bool = False
    labelled_at: datetime | None = None

class LabellingResult(BaseModel):
    subject_id: UUID
    topics_labelled: int
    topics_failed: int
    labels: list[TopicLabel]
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Implement keyword extraction (c-TF-IDF + KeyBERT) | Keywords are meaningful |
| 2 | Implement representative utterance selection | Top-N utterances returned per topic |
| 3 | Implement LLM labelling prompt | Labels are accurate on test set |
| 4 | Implement label persistence to topics table | T31.1, T31.2, T31.3 pass |
| 5 | Implement user label edit API | T31.3 passes |
| 6 | Handle single-member clusters | T31.4 passes |
| 7 | Handle labelling failures gracefully | T31.5 passes |

**Atomic Sub-tasks:**
1. c-TF-IDF keyword extraction via BERTopic
2. KeyBERT keyword extraction for side keywords
3. Representative utterance selection (top-N by centroid distance)
4. LLM labelling prompt construction
5. LLM labelling execution via local vLLM
6. Label and keyword persistence to `topics` table
7. User label edit API endpoint
8. Graceful failure handling

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Single-member cluster | Use the single utterance as context; label from it |
| LLM labelling fails | Set placeholder label; pipeline continues |
| User label edit exists | Do not overwrite; respect `is_user_edited` flag |
| LLM returns empty label | Retry once; if still empty, use placeholder |
| Keywords are empty | Use first 5 words of most representative utterance |
| Topic has no utterances | Skip labelling; log warning |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Pipeline pattern: keywords → representative utterances → LLM label → persist
- Strategy pattern: pluggable keyword extraction methods
- Guard pattern: `is_user_edited` flag prevents overwrites

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`keyword_extractor.py`, `llm_labeller.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Labelling Service Interface:**
```python
# src/services/labelling.py
class TopicLabeller:
    def __init__(self, config: LabellingConfig):
        self.config = config

    async def label_subject(
        self, subject_id: UUID
    ) -> LabellingResult:
        """Label all topics in a subject."""
        topics = await topic_repo.get_all(subject_id)
        results = []

        for topic in topics:
            try:
                label = await self._label_topic(subject_id, topic)
                await topic_repo.update_label(
                    subject_id, topic.id, label.label, label.keywords
                )
                results.append(label)
            except Exception as e:
                logger.error(f"Labelling failed for topic {topic.id}: {e}")
                placeholder = TopicLabel(
                    topic_id=topic.id,
                    label=f"Topic {topic.id}",
                    keywords=[],
                    representative_utterances=[],
                )
                await topic_repo.update_label(
                    subject_id, topic.id, placeholder.label, []
                )
                results.append(placeholder)

        return LabellingResult(
            subject_id=subject_id,
            topics_labelled=sum(1 for r in results if r.label != f"Topic {r.topic_id}"),
            topics_failed=sum(1 for r in results if r.label.startswith("Topic ")),
            labels=results,
        )

    async def _label_topic(
        self, subject_id: UUID, topic: TopicOutput
    ) -> TopicLabel:
        """Label a single topic."""
        # 1. Extract keywords
        keywords = await self._extract_keywords(subject_id, topic.id)

        # 2. Select representative utterances
        utterances = await self._select_representative_utterances(
            subject_id, topic.id
        )

        # 3. LLM label
        label = await self._llm_label(keywords, utterances)

        return TopicLabel(
            topic_id=topic.id,
            label=label,
            keywords=keywords,
            representative_utterances=utterances,
            labelled_at=datetime.now(timezone.utc),
        )

    async def _extract_keywords(
        self, subject_id: UUID, topic_id: UUID
    ) -> list[str]:
        """Extract keywords via c-TF-IDF + KeyBERT."""
        utterances = await utterance_repo.get_by_topic(subject_id, topic_id)
        texts = [u.text for u in utterances]

        # c-TF-IDF via BERTopic
        ctfidf = self.topic_model.extract_topic_labels(texts)

        # KeyBERT for side keywords
        from keybert import KeyBERT
        kw_model = KeyBERT()
        keywords = kw_model.extract_keywords(
            " ".join(texts),
            keyphrase_ngram_range=(1, 2),
            stop_words="english",
            top_n=self.config.top_n_keywords,
        )
        return [kw for kw, _ in keywords]

    async def _select_representative_utterances(
        self, subject_id: UUID, topic_id: UUID
    ) -> list[str]:
        """Select top-N utterances closest to topic centroid."""
        topic = await topic_repo.get(subject_id, topic_id)
        utterances = await utterance_repo.get_by_topic(subject_id, topic_id)

        # Compute distances to centroid
        distances = []
        for utt in utterances:
            if utt.embedding is not None:
                dist = cosine_distance(topic.centroid, utt.embedding)
                distances.append((dist, utt.text))

        # Sort by distance (closest first)
        distances.sort(key=lambda x: x[0])
        return [text for _, text in distances[:self.config.top_n_utterances]]

    async def _llm_label(
        self, keywords: list[str], utterances: list[str]
    ) -> str:
        """Use LLM to generate a topic label."""
        prompt = f"""Based on these keywords and utterances, generate a concise topic label (max {self.config.max_label_length} characters).

Keywords: {', '.join(keywords)}

Representative utterances:
{chr(10).join(f'- {u}' for u in utterances)}

Topic label:"""

        # Call local vLLM
        response = await llm_client.complete(
            prompt,
            model=self.config.llm_model,
            temperature=self.config.llm_temperature,
            max_tokens=50,
        )
        return response.strip()
```

**User Label Edit API:**
```python
# src/api/routes/topics.py
@router.put("/subjects/{subject_id}/topics/{topic_id}/label")
async def update_topic_label(
    subject_id: UUID,
    topic_id: UUID,
    label_update: TopicLabelUpdate,
) -> TopicResponse:
    """
    User can edit a topic label. Sets is_user_edited=True
    to prevent re-clustering from overwriting.
    """
    await topic_repo.update_label(
        subject_id, topic_id,
        label_update.label,
        label_update.keywords,
        is_user_edited=True,
    )
    return await topic_repo.get(subject_id, topic_id)
```

**Prompt Template:**
```
Based on these keywords and utterances, generate a concise topic label.
The label should be human-readable and accurately describe the topic.

Keywords: {keywords}

Representative utterances:
- {utterance_1}
- {utterance_2}
...

Topic label (max {max_length} characters):
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `LLM_ENDPOINT` | string | vLLM endpoint | `http://vllm:8000/v1` |
| `LLM_MODEL` | string | LLM model name | `phi-3-mini-3.8b-4bit` |
| `TOP_N_UTTERANCES` | int | Representative utterances for labelling | `10` |
| `TOP_N_KEYWORDS` | int | Keywords per topic | `10` |
| `LLM_TEMPERATURE` | float | LLM temperature | `0.3` |

**Third-Party Integration Contracts:**
- vLLM: LLM inference endpoint (S36)
- KeyBERT: keyword extraction
- BERTopic: c-TF-IDF extraction

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T31.1 | V | `pytest tests/test_labelling.py::test_keyword_relevance -v` | Extracted keywords judged relevant by human review (≥ 80% acceptable) |
| T31.2 | M | `pytest tests/test_labelling.py::test_llm_label_accuracy -v` | LLM topic labels judged accurate on 20 clusters (≥ 80%) |
| T31.3 | I | `pytest tests/test_labelling.py::test_user_edit_persists -v` | User label edit persists and is not overwritten by re-clustering |
| T31.4 | U | `pytest tests/test_labelling.py::test_single_member_cluster -v` | Labelling handles a single-member cluster without error |
| T31.5 | I | `pytest tests/test_labelling.py::test_labelling_failure_continues -v` | Labelling failure leaves a placeholder label; pipeline continues |

**Test Case Details (Given/When/Then):**

**T31.1 — Keyword relevance**
- **Given:** 20 labelled topics with known keywords
- **When:** keyword extraction is run
- **Then:** ≥ 80% of extracted keywords are judged relevant by human review

**T31.2 — LLM label accuracy**
- **Given:** 20 topics with known labels
- **When:** LLM labelling is run
- **Then:** ≥ 80% of generated labels are judged accurate by human review

**T31.3 — User edit persists**
- **Given:** a topic with user-edited label "Photosynthesis Mechanisms"
- **When:** re-clustering and re-labelling is run
- **Then:** the label remains "Photosynthesis Mechanisms"; `is_user_edited` flag preserved

**T31.4 — Single-member cluster**
- **Given:** a topic with exactly 1 member utterance
- **When:** labelling is run
- **Then:** the topic receives a label based on that single utterance; no error

**T31.5 — Labelling failure continues pipeline**
- **Given:** LLM service is temporarily unavailable
- **When:** labelling is run on 20 topics
- **Then:** failed topics get placeholder labels; remaining topics are labelled; pipeline completes

**Verification Commands:**
```bash
uv run pytest tests/test_labelling.py -v -k "S31" && \
uv run mypy --strict src/ml/labelling/ && \
uv run ruff check src/ml/labelling/
```

**Exit Criteria:**
- [ ] T31.1 passes — keywords are relevant (≥ 80%)
- [ ] T31.2 passes — LLM labels are accurate (≥ 80%)
- [ ] T31.3 passes — user edits persist through re-clustering
- [ ] T31.4 passes — single-member clusters handled
- [ ] T31.5 passes — failure leaves placeholder, pipeline continues
- [ ] Topics carry human-meaningful labels and keywords

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- KeyBERT keyword extraction on very short texts (< 5 words) produces poor results — use fallback keywords
- LLM may hallucinate labels not grounded in utterances — use low temperature (0.3)
- `is_user_edited` flag must be checked before overwriting — re-clustering must not clobber user work
- c-TF-IDF requires multiple documents; single-member cluster needs special handling

**Fallback Instructions:**
- If LLM labelling fails: use keyword concatenation as placeholder label
- If keywords are empty: use first 5 words of most representative utterance
- If user edit is detected: skip labelling for that topic entirely

**Rollback Procedure:**
- Revert label changes via API: `PUT /subjects/{id}/topics/{id}/label`
- No schema migration rollback needed
- User edits are never overwritten by automation

---

### 9. Observability (if applicable)

**Metrics Added:**
- `labelling_topics_labelled`: counter of topics labelled (labels: success, failed)
- `labelling_llm_latency_seconds`: histogram of LLM labelling latency
- `labelling_keyword_count`: histogram of keywords per topic
- `labelling_user_edit_ratio`: gauge of user-edited labels / total labels

**Tracing/Logging:**
- Span: `labelling.label_topic` with attributes (topic_id, keyword_count, llm_latency_ms)
- Log: INFO on labelling completion with summary
- Log: WARN on labelling failure with placeholder
- Log: INFO on user label edit

**Alerts:**
- Labelling failure rate > 30%: LLM service issue
- Average keyword count < 3: extraction issue

---

### 10. Exit Checklist

- [ ] All tests pass (T31.1, T31.2, T31.3, T31.4, T31.5)
- [ ] Keywords extracted and judged relevant
- [ ] LLM labels generated and accurate
- [ ] User label edits persist through re-clustering
- [ ] Single-member clusters handled
- [ ] Labelling failures produce placeholders, pipeline continues
- [ ] Topics carry human-meaningful labels and keywords

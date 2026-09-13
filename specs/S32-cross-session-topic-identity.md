# S32 — Cross-Session Topic Identity
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** For each new segment, nearest-centroid match against the subject's existing topics via pgvector. Above threshold → link to existing topic (FR-5.4); below → create new topic (FR-5.5). Incremental centroid update. Full re-cluster flow triggered every N sessions.

**Component Boundaries:**
- **Allowed:** `src/services/topic_identity.py`, `src/db/repositories/topic_repo.py`, `src/ml/clustering/recluster.py`, `tests/test_topic_identity.py`
- **Off-limits:** Clustering algorithm (S30), topic labelling (S31), A1 relevance (S41)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| pgvector | 0.5.0 | Nearest-centroid vector queries |
| SQLAlchemy | 2.0.52 | ORM for topic operations |
| scikit-learn | 1.5.1 | Centroid distance computation |
| pytest | 8.x | Tests |

---

### 2. State Machine & Domain Schemas

**Topic Identity State:**
```
For each new segment:
  ↓
Query existing topic centroids in subject
  ↓
Compute cosine distance to nearest centroid
  ↓
distance < threshold → LINK to existing topic (FR-5.4)
distance >= threshold → CREATE new topic (FR-5.5)
  ↓
Update centroid incrementally (running mean)
```

**Re-cluster Schedule:**
```
Sessions 1-5: re-cluster every session (cold start, §12.5)
Sessions 6-N: re-cluster every 10 sessions (default)
Full re-cluster: UMAP + HDBSCAN on all segment centroids
```

**Pydantic Models:**
```python
# src/services/topic_identity.py
from pydantic import BaseModel, Field


class TopicIdentityConfig(BaseModel):
    match_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Cosine distance threshold; below = match, above = new topic",
    )
    recluster_interval: int = Field(
        default=10, ge=1, description="Full re-cluster every N sessions"
    )
    cold_start_sessions: int = Field(
        default=5, ge=1, description="Re-cluster every session for first N sessions"
    )
    centroid_decay: float = Field(
        default=0.9, ge=0.5, le=1.0, description="Decay factor for incremental centroid update"
    )


class TopicMatch(BaseModel):
    topic_id: UUID
    distance: float
    is_match: bool  # True if distance < threshold
    centroid_version: int  # Incremented on each update


class IdentityResult(BaseModel):
    session_id: UUID
    subject_id: UUID
    segment_matches: list[SegmentMatch]
    new_topics_created: int
    existing_topics_linked: int
    recluster_triggered: bool


class SegmentMatch(BaseModel):
    segment_id: UUID
    topic_id: UUID
    distance: float
    is_new_topic: bool
```

**Incremental Centroid Update:**
```python
def update_centroid(
    old_centroid: list[float],
    new_member_embedding: list[float],
    member_count: int,
    decay: float = 0.9,
) -> list[float]:
    """
    Incremental centroid update with decay.
    new_centroid = decay * old_centroid + (1 - decay) * new_member_embedding
    This allows the centroid to shift gradually as new sessions arrive.
    """
    import numpy as np

    old = np.array(old_centroid)
    new = np.array(new_member_embedding)
    updated = decay * old + (1 - decay) * new
    # Re-normalize to unit length for cosine similarity
    norm = np.linalg.norm(updated)
    if norm > 0:
        updated = updated / norm
    return updated.tolist()
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Implement nearest-centroid query via pgvector | Query returns distances |
| 2 | Implement match/create decision logic | T32.1, T32.2 pass |
| 3 | Implement incremental centroid update | T32.3 passes |
| 4 | Implement re-cluster trigger logic | T32.4 passes |
| 5 | Implement subject-boundary enforcement | T32.5 passes |
| 6 | Implement threshold sensitivity analysis | T32.6 passes |
| 7 | Run performance benchmark | T32.7 passes |

**Atomic Sub-tasks:**
1. Nearest-centroid pgvector query for existing topics
2. Match/create decision based on distance threshold
3. Incremental centroid update with decay
4. Session counter and re-cluster trigger
5. Subject-boundary enforcement on matching queries
6. Threshold sensitivity analysis on S05 labels
7. Full re-cluster flow that preserves user-edited labels

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| No existing topics in subject | First segment creates new topic |
| All distances above threshold | All segments create new topics |
| Centroid drift over time | Re-cluster corrects drift periodically |
| User-edited label lost on re-cluster | Preserve `is_user_edited` flag during re-cluster |
| Cross-subject query attempted | Reject at repository level; subject_id enforced |
| Threshold too tight | Too many new topics; loosen threshold |
| Threshold too loose | Topics merge incorrectly; tighten threshold |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: pluggable distance metrics
- Observer pattern: session counter triggers re-cluster
- Guard pattern: subject-boundary enforcement

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`topic_identity.py`, `recluster.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Topic Identity Service:**
```python
# src/services/topic_identity.py
class TopicIdentityService:
    def __init__(self, config: TopicIdentityConfig):
        self.config = config

    async def identify_segment_topics(
        self,
        subject_id: UUID,
        session_id: UUID,
        segment_centroids: list[tuple[UUID, list[float]]],
    ) -> IdentityResult:
        """
        For each segment centroid, find or create a topic.
        Returns identity results and triggers re-cluster if needed.
        """
        matches = []
        new_count = 0
        linked_count = 0

        for seg_id, centroid in segment_centroids:
            # 1. Query nearest existing topic centroid
            nearest = await self._find_nearest_topic(subject_id, centroid)

            if nearest and nearest.distance < self.config.match_threshold:
                # 2a. Link to existing topic
                await self._link_segment_to_topic(subject_id, seg_id, nearest.topic_id)
                await self._update_centroid_incremental(subject_id, nearest.topic_id, centroid)
                matches.append(
                    SegmentMatch(
                        segment_id=seg_id,
                        topic_id=nearest.topic_id,
                        distance=nearest.distance,
                        is_new_topic=False,
                    )
                )
                linked_count += 1
            else:
                # 2b. Create new topic
                new_topic_id = await self._create_topic(subject_id, centroid)
                await self._link_segment_to_topic(subject_id, seg_id, new_topic_id)
                matches.append(
                    SegmentMatch(
                        segment_id=seg_id,
                        topic_id=new_topic_id,
                        distance=nearest.distance if nearest else 1.0,
                        is_new_topic=True,
                    )
                )
                new_count += 1

        # 3. Check if re-cluster is needed
        session_count = await self._increment_session_counter(subject_id)
        recluster = self._should_recluster(session_count)

        if recluster:
            await self._trigger_recluster(subject_id)

        return IdentityResult(
            session_id=session_id,
            subject_id=subject_id,
            segment_matches=matches,
            new_topics_created=new_count,
            existing_topics_linked=linked_count,
            recluster_triggered=recluster,
        )

    async def _find_nearest_topic(
        self, subject_id: UUID, centroid: list[float]
    ) -> TopicMatch | None:
        """Find nearest topic centroid via pgvector."""
        result = await topic_repo.nearest_centroid(subject_id, centroid, k=1)
        if not result:
            return None
        topic, distance = result[0]
        return TopicMatch(
            topic_id=topic.id,
            distance=distance,
            is_match=distance < self.config.match_threshold,
            centroid_version=topic.centroid_version,
        )

    async def _update_centroid_incremental(
        self,
        subject_id: UUID,
        topic_id: UUID,
        new_centroid: list[float],
    ) -> None:
        """Update topic centroid incrementally with decay."""
        topic = await topic_repo.get(subject_id, topic_id)
        updated = update_centroid(
            topic.centroid, new_centroid, topic.member_count, self.config.centroid_decay
        )
        await topic_repo.update_centroid(subject_id, topic_id, updated)

    def _should_recluster(self, session_count: int) -> bool:
        """Determine if full re-cluster is needed."""
        if session_count <= self.config.cold_start_sessions:
            return True  # Re-cluster every session during cold start
        return session_count % self.config.recluster_interval == 0
```

**Re-cluster Flow:**
```python
# src/ml/clustering/recluster.py
class ReclusterService:
    async def recluster_subject(self, subject_id: UUID) -> ClusteringResult:
        """
        Full re-cluster of all segment centroids within a subject.
        Preserves user-edited labels.
        """
        # 1. Get all existing topics with user edits
        existing_topics = await topic_repo.get_all(subject_id)
        user_edited = {t.id: t for t in existing_topics if t.is_user_edited}

        # 2. Get all segment centroids
        segments = await segment_repo.get_all_with_embeddings(subject_id)
        centroids = [self._compute_centroid(s) for s in segments]

        # 3. Run BERTopic (same as S30)
        topic_labels, outlier_scores = self._run_bertopic(centroids)

        # 4. Create new topic mapping, preserving user edits
        new_topics = []
        for topic_num in set(topic_labels) - {-1}:
            mask = topic_labels == topic_num
            centroid = np.mean([centroids[i] for i, m in enumerate(mask) if m], axis=0)

            # Check if any segment in this cluster was previously user-edited
            preserved_label = None
            for seg_idx, is_member in enumerate(mask):
                if is_member:
                    seg_id = segment_ids[seg_idx]
                    for old_topic_id, old_topic in user_edited.items():
                        if await topic_repo.segment_belongs_to_topic(
                            subject_id, seg_id, old_topic_id
                        ):
                            preserved_label = old_topic.label
                            break

            topic = TopicOutput(
                topic_id=uuid4(),
                label=preserved_label,  # Preserve user edit
                centroid=centroid.tolist(),
                member_count=int(mask.sum()),
                is_user_edited=preserved_label is not None,
            )
            await topic_repo.create(subject_id, topic)
            new_topics.append(topic)

        # 5. Update all segment-topic links
        await self._update_segment_links(subject_id, segment_ids, topic_labels, new_topics)

        # 6. Update outlier scores
        await self._update_outlier_scores(subject_id, segment_ids, outlier_scores)

        return ClusteringResult(
            subject_id=subject_id,
            topics=new_topics,
            outlier_count=int((topic_labels == -1).sum()),
            total_segments=len(centroids),
        )
```

**Subject-Boundary Enforcement:**
```python
# src/db/repositories/topic_repo.py
async def nearest_centroid(
    self,
    subject_id: UUID,
    centroid: list[float],
    k: int = 1,
) -> list[tuple[Topic, float]]:
    """
    Find k nearest topic centroids within a subject.
    Subject boundary enforced at query level.
    """
    result = await self.session.execute(
        text("""
            SELECT t.*, t.centroid <=> :centroid AS distance
            FROM topics t
            WHERE t.subject_id = :subject_id
            ORDER BY t.centroid <=> :centroid
            LIMIT :k
        """),
        {"subject_id": subject_id, "centroid": str(centroid), "k": k},
    )
    return [(Topic(**row), row["distance"]) for row in result]
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `TOPIC_MATCH_THRESHOLD` | float | Cosine distance threshold for matching | `0.3` |
| `RECLUSTER_INTERVAL` | int | Full re-cluster every N sessions | `10` |
| `COLD_START_SESSIONS` | int | Re-cluster every session for first N | `5` |
| `CENTROID_DECAY` | float | Decay factor for incremental update | `0.9` |

**Third-Party Integration Contracts:**
- pgvector: vector similarity queries
- BERTopic: re-cluster pipeline (same as S30)
- Session lifecycle (S23): session counter

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T32.1 | V | `pytest tests/test_topic_identity.py::test_cross_session_recognition -v` | Topic taught across 3 sessions recognised as one topic |
| T32.2 | V | `pytest tests/test_topic_identity.py::test_new_topic_created -v` | Genuinely new topic creates new partition |
| T32.3 | I | `pytest tests/test_topic_identity.py::test_centroid_update -v` | Centroids update incrementally and correctly |
| T32.4 | I | `pytest tests/test_topic_identity.py::test_recluster_preserves_labels -v` | Full re-cluster preserves user-edited labels |
| T32.5 | I | `pytest tests/test_topic_identity.py::test_no_cross_subject -v` | Matching queries never cross subject boundaries |
| T32.6 | V | `pytest tests/test_topic_identity.py::test_threshold_sensitivity -v` | Threshold sensitivity analysed against S05 labels |
| T32.7 | P | `pytest tests/test_topic_identity.py::test_matching_performance -v` | Matching 50 segments against 50 topics in < 1s |

**Test Case Details (Given/When/Then):**

**T32.1 — Cross-session topic recognition (AC-4)**
- **Given:** 3 separate sessions all discussing "photosynthesis" with segment centroids
- **When:** each session's segments are matched against existing topics
- **Then:** all 3 sessions' photosynthesis segments link to the same topic; not 3 separate topics

**T32.2 — New topic creation**
- **Given:** existing topics covering photosynthesis and mitosis
- **When:** a session segment about "cellular respiration" (genuinely new) is matched
- **Then:** a new topic is created (distance > threshold); not force-matched to existing

**T32.3 — Incremental centroid update**
- **Given:** a topic with centroid C and 5 member segments
- **When:** a new segment with centroid N is linked to the topic
- **Then:** topic centroid is updated to `0.9*C + 0.1*N` (with decay); member_count incremented

**T32.4 — Re-cluster preserves user edits**
- **Given:** a topic with user-edited label "Photosynthesis Mechanisms"
- **When:** full re-cluster is triggered
- **Then:** the new topic cluster containing those segments preserves the label; `is_user_edited` flag intact

**T32.5 — No cross-subject matching**
- **Given:** topics in subject A and segments in subject B
- **When:** matching is attempted for subject B's segments
- **Then:** only subject B's topics are queried; subject A's topics are never considered

**T32.6 — Threshold sensitivity analysis**
- **Given:** S05 labelled topics with known boundaries
- **When:** matching is run at thresholds [0.1, 0.2, 0.3, 0.4, 0.5]
- **Then:** optimal threshold is documented; chosen value (0.3) justified by precision/recall tradeoff

**T32.7 — Matching performance**
- **Given:** 50 segments and 50 existing topics in one subject
- **When:** nearest-centroid matching is run
- **Then:** completes in under 1 second

**Verification Commands:**
```bash
uv run pytest tests/test_topic_identity.py -v -k "S32" && \
uv run mypy --strict src/services/topic_identity.py && \
uv run ruff check src/services/topic_identity.py
```

**Exit Criteria:**
- [ ] T32.1 passes — cross-session topic recognition (AC-4)
- [ ] T32.2 passes — new topics created correctly
- [ ] T32.3 passes — incremental centroid update
- [ ] T32.4 passes — re-cluster preserves user-edited labels
- [ ] T32.5 passes — no cross-subject matching
- [ ] T32.6 passes — threshold sensitivity analysed
- [ ] T32.7 passes — matching 50 topics in < 1s
- [ ] Topic identity accumulates correctly across a semester within a subject

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Centroid drift without re-cluster causes topics to merge incorrectly — re-cluster is essential
- Cold start (sessions 1-5) requires tighter re-cluster schedule — per §12.5
- User-edited labels must be preserved across re-cluster — `is_user_edited` flag is the guard
- Cross-subject queries are a data integrity violation — enforce at repository level, not just application
- Threshold of 0.3 is a starting point — must be tuned against S05 labels (T32.6)

**Fallback Instructions:**
- If too many new topics: lower threshold (e.g., 0.2)
- If topics merge incorrectly: raise threshold (e.g., 0.4)
- If centroid drift detected: increase re-cluster frequency
- If re-cluster loses labels: check `is_user_edited` preservation logic

**Rollback Procedure:**
- Delete topics created in error: `DELETE FROM topics WHERE subject_id = $1 AND created_at > $2`
- Reset session counter: `UPDATE topic_identity_counters SET count = 0 WHERE subject_id = $1`
- Revert to previous centroid values from backup
- No schema migration rollback needed

---

### 9. Observability (if applicable)

**Metrics Added:**
- `topic_identity_matches_total`: counter of matches (labels: new_topic, linked, subject_id)
- `topic_identity_distance_histogram`: histogram of match distances
- `topic_identity_recluster_total`: counter of re-cluster triggers
- `topic_identity_session_count`: gauge of sessions processed per subject
- `topic_identity_matching_duration_seconds`: histogram of matching time

**Tracing/Logging:**
- Span: `topic_identity.identify_segment` with attributes (session_id, segment_count, new_topics, linked_topics)
- Span: `topic_identity.recluster` with attributes (subject_id, old_topic_count, new_topic_count)
- Log: INFO on matching completion with summary
- Log: WARN on re-cluster trigger
- Log: INFO on user-edited label preservation

**Alerts:**
- New topic ratio > 50%: threshold may be too high
- Re-cluster frequency too high: interval may need adjustment
- Matching time > 5s for 50 topics: pgvector index issue

---

### 10. Exit Checklist

- [ ] All tests pass (T32.1, T32.2, T32.3, T32.4, T32.5, T32.6, T32.7)
- [ ] Cross-session topic recognition works (AC-4)
- [ ] New topics created for genuinely new content
- [ ] Incremental centroid update with decay
- [ ] Re-cluster preserves user-edited labels
- [ ] No cross-subject matching
- [ ] Threshold sensitivity analysed and justified
- [ ] Matching performance < 1s for 50 topics
- [ ] Topic identity accumulates across semester within subject

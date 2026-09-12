# S30 — Topic Clustering
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Task T3 — mean-pool each segment's member embeddings, then cluster segment embeddings (not raw utterances) with UMAP + HDBSCAN via BERTopic. Persist `topics` rows with centroid and keywords. Store the HDBSCAN outlier score on each utterance for downstream A1 use.

**Component Boundaries:**
- **Allowed:** `src/ml/clustering/`, `src/services/clustering.py`, `src/db/repositories/topic_repo.py`, `tests/test_clustering.py`
- **Off-limits:** Topic labelling (S31), cross-session identity (S32), A1 relevance filter (S41)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| BERTopic | 0.16.x | Topic modelling pipeline |
| UMAP | 0.5.x | Dimensionality reduction |
| HDBSCAN | 0.13.x | Density-based clustering |
| scikit-learn | 1.5.1 | Centroid computation, metrics |
| numpy | 1.26.x | Array operations |
| pytest | 8.x | Tests |

---

### 2. State Machine & Domain Schemas

**Clustering Pipeline:**
```
Input: segmented session with windowed embeddings
  ↓
Mean-pool each segment's member embeddings → segment centroids
  ↓
Collect all segment centroids within subject
  ↓
UMAP dimensionality reduction (1024 → 5)
  ↓
HDBSCAN clustering → topic assignments + outlier scores
  ↓
Output: topics table rows, utterance outlier scores
```

**Pydantic Models:**
```python
# src/ml/clustering/config.py
from pydantic import BaseModel, Field

class ClusteringConfig(BaseModel):
    umap_n_neighbors: int = Field(default=15, ge=2)
    umap_n_components: int = Field(default=5, ge=2, le=10)
    umap_metric: str = "cosine"
    umap_min_dist: float = Field(default=0.1, ge=0.0, le=1.0)
    hdbscan_min_cluster_size: int = Field(default=5, ge=2)
    hdbscan_min_samples: int = Field(default=3, ge=1)
    hdbscan_metric: str = "euclidean"
    hdbscan_cluster_selection_method: str = "eom"
    outlier_score_percentile: float = Field(default=0.1, ge=0.0, le=0.5)

class TopicOutput(BaseModel):
    topic_id: UUID
    label: str | None = None
    centroid: list[float]
    member_count: int
    keywords: list[str] | None = None
    is_outlier: bool = False

class ClusteringResult(BaseModel):
    subject_id: UUID
    topics: list[TopicOutput]
    outlier_count: int
    total_segments: int
    purity: float | None = None  # If ground truth available
```

**Topics Table Schema (from S09 extension):**
```sql
CREATE TABLE topics (
    subject_id    UUID        NOT NULL,
    id            UUID        NOT NULL DEFAULT gen_random_uuid(),
    label         TEXT,
    centroid      vector(1024),
    member_count  INTEGER     NOT NULL DEFAULT 0,
    keywords      TEXT[],
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, id)
) PARTITION BY LIST (subject_id);
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Implement segment centroid computation (mean-pool) | Centroids are 1024-dim vectors |
| 2 | Implement BERTopic pipeline with UMAP + HDBSCAN | Pipeline fits and produces topics |
| 3 | Implement topic persistence to `topics` table | T30.1 passes |
| 4 | Implement outlier score persistence on utterances | T30.5 passes |
| 5 | Scope clustering within one subject | T30.3 passes |
| 6 | Run purity evaluation against S05 labels | T30.2 passes |
| 7 | Test multi-topic session | T30.3 passes |
| 8 | Run performance benchmark | T30.6 passes |

**Atomic Sub-tasks:**
1. Segment centroid computation (mean-pool of member embeddings)
2. BERTopic pipeline with UMAP + HDBSCAN configuration
3. Topic row persistence with centroid and keywords
4. Outlier score extraction and persistence on utterances
5. Subject-scoped clustering (no cross-subject vectors)
6. Purity evaluation against S05 ground truth

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| All segments are outliers | HDBSCAN returns no clusters; all utterances marked outlier |
| Single segment in subject | One topic or outlier; no clustering possible |
| HDBSCAN produces 1 cluster | Valid; all segments belong to one topic |
| Centroid computation on empty segment | Skip segment; log warning |
| UMAP input dimension mismatch | Validate embeddings are 1024-dim before UMAP |
| Outlier score threshold too aggressive | Too many outliers; increase percentile |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Pipeline pattern: sequential UMAP → HDBSCAN → persistence
- Repository pattern: `TopicRepository` for DB operations
- Config pattern: `ClusteringConfig` Pydantic model

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`bertopic_pipeline.py`, `centroid.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Clustering Service Interface:**
```python
# src/services/clustering.py
class ClusteringService:
    def __init__(self, config: ClusteringConfig):
        self.config = config
        self.topic_model = None  # Lazy init

    async def cluster_subject(
        self,
        subject_id: UUID,
    ) -> ClusteringResult:
        """
        Cluster all segments within a subject.
        Segments first (S28), then cluster (per §12.2).
        """
        # 1. Get all segments with embeddings for this subject
        segments = await segment_repo.get_all_with_embeddings(subject_id)

        # 2. Compute segment centroids
        centroids, segment_ids = self._compute_centroids(segments)

        # 3. Cluster with BERTopic
        topic_labels, outlier_scores = self._run_bertopic(centroids)

        # 4. Persist topics
        topics = await self._persist_topics(
            subject_id, centroids, topic_labels, topic_ids
        )

        # 5. Persist outlier scores on utterances
        await self._persist_outlier_scores(
            subject_id, segment_ids, outlier_scores
        )

        return ClusteringResult(
            subject_id=subject_id,
            topics=topics,
            outlier_count=int((topic_labels == -1).sum()),
            total_segments=len(centroids),
        )

    def _compute_centroids(
        self, segments: list[Segment]
    ) -> tuple[list[list[float]], list[UUID]]:
        """Mean-pool each segment's member embeddings into a centroid."""
        centroids = []
        segment_ids = []
        for seg in segments:
            utts = await utterance_repo.get_by_segment(seg.subject_id, seg.id)
            embeddings = [u.embedding for u in utts if u.embedding is not None]
            if not embeddings:
                continue
            centroid = np.mean(embeddings, axis=0).tolist()
            centroids.append(centroid)
            segment_ids.append(seg.id)
        return centroids, segment_ids

    def _run_bertopic(
        self, centroids: list[list[float]]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Run BERTopic on segment centroids."""
        from bertopic import BERTopic
        from umap import UMAP
        from hdbscan import HDBSCAN

        umap_model = UMAP(
            n_neighbors=self.config.umap_n_neighbors,
            n_components=self.config.umap_n_components,
            metric=self.config.umap_metric,
            min_dist=self.config.umap_min_dist,
            random_state=42,
        )
        hdbscan_model = HDBSCAN(
            min_cluster_size=self.config.hdbscan_min_cluster_size,
            min_samples=self.config.hdbscan_min_samples,
            metric=self.config.hdbscan_metric,
            cluster_selection_method=self.config.hdbscan_cluster_selection_method,
        )

        self.topic_model = BERTopic(
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,
            calculate_probabilities=True,
        )

        topic_labels = self.topic_model.fit_transform(
            [json.dumps(c) for c in centroids],
            np.array(centroids),
        )

        # Extract outlier scores from HDBSCAN
        outlier_scores = self.topic_model.hdbscan_model.outlier_scores_

        return topic_labels, outlier_scores

    async def _persist_topics(
        self,
        subject_id: UUID,
        centroids: list[list[float]],
        topic_labels: np.ndarray,
        topic_ids: list[UUID],
    ) -> list[TopicOutput]:
        """Create topic rows for each unique non-outlier topic."""
        unique_topics = set(topic_labels) - {-1}
        topics = []
        for topic_id_num in unique_topics:
            mask = topic_labels == topic_id_num
            member_centroids = [centroids[i] for i, m in enumerate(mask) if m]
            centroid = np.mean(member_centroids, axis=0).tolist()

            topic = TopicOutput(
                topic_id=uuid4(),
                label=None,  # Will be set by S31
                centroid=centroid,
                member_count=int(mask.sum()),
                is_outlier=False,
            )
            await topic_repo.create(subject_id, topic)
            topics.append(topic)

        return topics
```

**Outlier Score Persistence:**
```python
async def _persist_outlier_scores(
    self,
    subject_id: UUID,
    segment_ids: list[UUID],
    outlier_scores: np.ndarray,
) -> None:
    """Store HDBSCAN outlier score on each utterance in each segment."""
    for seg_id, score in zip(segment_ids, outlier_scores):
        utts = await utterance_repo.get_by_segment(subject_id, seg_id)
        for utt in utts:
            await utterance_repo.update_outlier_score(
                subject_id, utt.id, float(score)
            )
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `UMAP_N_NEIGHBORS` | int | UMAP n_neighbors | `15` |
| `UMAP_N_COMPONENTS` | int | UMAP n_components | `5` |
| `HDBSCAN_MIN_CLUSTER_SIZE` | int | HDBSCAN min_cluster_size | `5` |
| `HDBSCAN_MIN_SAMPLES` | int | HDBSCAN min_samples | `3` |
| `OUTLIER_SCORE_PERCENTILE` | float | Outlier score threshold | `0.1` |

**Third-Party Integration Contracts:**
- BERTopic: topic modelling pipeline
- UMAP: dimensionality reduction
- HDBSCAN: density-based clustering
- pgvector: vector storage from S09

**Version Pins:**
- BERTopic >= 0.16.0
- UMAP >= 0.5.0
- HDBSCAN >= 0.13.0

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T30.1 | I | `pytest tests/test_clustering.py::test_clustering_produces_topics -v` | Clustering produces topics; each segment assigned a topic or outlier |
| T30.2 | V | `pytest tests/test_clustering.py::test_purity -v` | Purity > 0.70 against S05 topic labels |
| T30.3 | V | `pytest tests/test_clustering.py::test_multi_topic_session -v` | Session with 2+ topics yields ≥ 2 clusters |
| T30.4 | I | `pytest tests/test_clustering.py::test_subject_scoping -v` | Clustering scoped within one subject; no cross-subject vectors |
| T30.5 | I | `pytest tests/test_clustering.py::test_outlier_scores_persisted -v` | Outlier scores persisted on utterances |
| T30.6 | P | `pytest tests/test_clustering.py::test_clustering_performance -v` | 31k vectors clustered in < 5 min |
| T30.7 | I | `pytest tests/test_clustering.py::test_contiguous_topic_assignment -v` | Topic assignments are contiguous within a segment |

**Test Case Details (Given/When/Then):**

**T30.1 — Clustering produces topics**
- **Given:** a subject with 50 segmented sessions and windowed embeddings
- **When:** `cluster_subject()` is called
- **Then:** topics are created in the `topics` table; each segment has a topic_id or is marked outlier

**T30.2 — Purity > 0.70**
- **Given:** S05 labelled transcripts with known topic labels
- **When:** clustering is run and topic assignments compared to ground truth
- **Then:** purity > 0.70

**T30.3 — Multi-topic session yields ≥ 2 clusters**
- **Given:** a session covering photosynthesis and mitosis (two distinct topics)
- **When:** clustering is run on that session's segments
- **Then:** at least 2 non-outlier clusters are produced

**T30.4 — Subject scoping**
- **Given:** two subjects with their own segments
- **When:** clustering is run for subject A
- **Then:** no segments or embeddings from subject B are included in the clustering

**T30.5 — Outlier scores persisted**
- **Given:** a clustered subject with outlier segments
- **When:** utterances in outlier segments are queried
- **Then:** each utterance has a non-null `outlier_score` value

**T30.6 — Clustering performance**
- **Given:** 31,000 segment centroids (representative workload)
- **When:** BERTopic clustering is run
- **Then:** completes in under 5 minutes

**T30.7 — Contiguous topic assignment**
- **Given:** a segmented session
- **When:** topics are assigned to segments
- **Then:** segments belonging to the same topic are contiguous (not interleaved)

**Verification Commands:**
```bash
uv run pytest tests/test_clustering.py -v -k "S30" && \
uv run mypy --strict src/ml/clustering/ && \
uv run ruff check src/ml/clustering/
```

**Exit Criteria:**
- [ ] T30.1 passes — clustering produces topics
- [ ] T30.2 passes — purity > 0.70
- [ ] T30.3 passes — multi-topic session yields ≥ 2 clusters
- [ ] T30.4 passes — subject-scoped clustering
- [ ] T30.5 passes — outlier scores persisted on utterances
- [ ] T30.6 passes — 31k vectors in < 5 min
- [ ] T30.7 passes — contiguous topic assignment
- [ ] Topics discovered within a subject at target purity
- [ ] Outlier scores available downstream for A1

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- BERTopic expects text input but we pass numerical embeddings — must use `embeddings` parameter, not `documents`
- UMAP random_state must be fixed for reproducibility
- HDBSCAN `min_cluster_size` too high produces too many outliers; too low produces too many small clusters
- Segment-first-then-cluster ordering is critical — clustering raw utterances produces worse results than clustering segment centroids
- Outlier scores from HDBSCAN are per-sample; need to propagate from segment centroid to constituent utterances

**Fallback Instructions:**
- If purity < 0.70: tune UMAP n_neighbors (5-50), HDBSCAN min_cluster_size (3-15)
- If too many outliers: reduce `outlier_score_percentile` or decrease HDBSCAN `min_cluster_size`
- If too many tiny clusters: increase HDBSCAN `min_cluster_size`

**Rollback Procedure:**
- Delete topics for affected subject: `DELETE FROM topics WHERE subject_id = $1`
- Reset outlier scores: `UPDATE utterances SET outlier_score = NULL WHERE subject_id = $1`
- No schema migration rollback needed

---

### 9. Observability (if applicable)

**Metrics Added:**
- `clustering_session_total`: counter of clustering runs (labels: subject_id)
- `clustering_topics_created`: gauge of topics per subject
- `clustering_outlier_ratio`: gauge of outlier segments / total segments
- `clustering_purity`: gauge of purity (when ground truth available)
- `clustering_duration_seconds`: histogram of clustering time

**Tracing/Logging:**
- Span: `clustering.cluster_subject` with attributes (subject_id, segment_count, topic_count, outlier_count)
- Log: INFO on clustering completion with summary
- Log: WARN on high outlier ratio (> 30%)

**Alerts:**
- Outlier ratio > 50%: HDBSCAN parameters may be wrong
- Purity < 0.60: clustering quality issue
- Clustering time > 10 min for 31k vectors: performance regression

---

### 10. Exit Checklist

- [ ] All tests pass (T30.1, T30.2, T30.3, T30.4, T30.5, T30.6, T30.7)
- [ ] Topics discovered within subject at purity > 0.70
- [ ] Each segment assigned a topic or marked outlier
- [ ] Outlier scores persisted on utterances for A1
- [ ] Clustering scoped within subject boundaries
- [ ] 31k vectors clustered in < 5 min
- [ ] Topic assignments contiguous within segments

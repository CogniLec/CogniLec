# S53 — Syllabus-Seeded Cold Start
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** When a syllabus exists before the first lecture, seed topic centroids from syllabus item embeddings so session 1 clusters against a known structure instead of discovering blind; apply tighter re-clustering cadence for sessions 2–5 while centroids are unstable.

**Component Boundaries:**
- **Allowed:** `src/services/clustering/seed.py`, `src/services/clustering/recluster.py`, `src/graph/session_hooks.py`, `tests/test_syllabus_seed.py`, `tests/test_early_session_recluster.py`
- **Off-limits:** A6 extraction (S50), coverage mapping (S52), topic discovery (S28–S32), embedding generation (S48), syllabus upload (S51)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| scikit-learn | 1.5.x | KMeans/HDBSCAN clustering with seed initialization |
| NumPy | 1.26.x | Centroid computation and similarity |
| pgvector | 0.8.x | Vector similarity queries for centroid seeding |
| SQLAlchemy | 2.0.52 | DB queries |
| pytest | 8.x | Integration tests |
| testcontainers | 4.6.x | PG-SYLLABUS + PG-MAIN for tests |

---

### 2. State Machine & Domain Schemas

**Cold Start State:**
```
NO_SYLLABUS → [no seeding, normal discovery]
SYLLABUS_EXISTS → SEEDING → SESSION_1_CLUSTERING (seeded)
                          → SESSIONS_2_5 (tight recluster cadence)
                          → SESSION_6+ (stable, normal cadence)
```

**Centroid Seeding Flow:**
```
syllabus_items (DB-3) → extract_embeddings → initial_centroids → session_1_cluster_init
                                    ↓ (as sessions accumulate)
                          observed_data → replace_seeds → stable_centroids
```

**Re-Clustering Cadence:**
```
Session 1: cluster with seeded centroids (no re-clustering needed)
Session 2: re-cluster after session (tight cadence)
Session 3: re-cluster after session (tight cadence)
Session 4: re-cluster after session (tight cadence)
Session 5: re-cluster after session (tight cadence)
Session 6+: re-cluster every N sessions (normal cadence, configurable)
```

**Pydantic Models:**
```python
# src/services/clustering/seed.py
from pydantic import BaseModel, Field
from enum import Enum

class SeedingStatus(str, Enum):
    NOT_SEEDED = "not_seeded"
    SEEDED = "seeded"
    STABILIZED = "stabilized"  # real data replaced initial seeds

class CentroidSeed(BaseModel):
    syllabus_item_id: UUID
    title: str
    embedding: list[float]  # 1024-dim vector
    initial_topic_id: UUID | None = None  # assigned after first clustering
    replaced_by_data: bool = False  # True when real session data replaces seed

class SeedingResult(BaseModel):
    subject_id: UUID
    status: SeedingStatus
    seed_count: int
    seeds: list[CentroidSeed]
    session_count: int  # number of sessions so far
    recluster_cadence: str  # "tight" | "normal"

class ReclusterConfig(BaseModel):
    """Configuration for re-clustering cadence."""
    tight_cadence_sessions: int = 5  # sessions 2–5 use tight cadence
    tight_cadence_recluster_after: bool = True  # re-cluster after every session
    normal_cadence_interval: int = 5  # re-cluster every N sessions after session 5
    min_topics_for_recluster: int = 3  # minimum topics to trigger re-clustering
    seed_replacement_threshold: float = 0.7  # cosine similarity to replace seed
```

**State Transition Rules:**
- No syllabus exists → normal topic discovery (no seeding, no change to existing flow)
- Syllabus exists before session 1 → seed centroids from syllabus item embeddings
- Session 1 uses seeded centroids for initial clustering
- Sessions 2–5: re-cluster after each session with tight cadence
- Session 6+: re-cluster every N sessions (normal cadence)
- As real sessions accumulate, seed centroids are gradually replaced by observed data
- When a seed centroid's nearest cluster center has cosine similarity > threshold with real data, the seed is marked as replaced
- If syllabus is uploaded AFTER session 1: seeding is not applied retroactively (too late for cold start)

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create centroid seeding service | Unit test: syllabus embeddings → initial centroids |
| 2 | Integrate seeding into session 1 clustering pipeline | Integration test: seeded clustering produces topic clusters |
| 3 | Implement re-cluster cadence logic (tight for sessions 2–5) | Integration test: sessions 2–5 trigger re-clustering |
| 4 | Implement seed replacement logic | Unit test: seeds replaced by observed data |
| 5 | Wire session hooks for post-session re-clustering | Integration test: session.complete triggers re-cluster |
| 6 | Add no-syllabus path (seeding is optional) | Integration test: no syllabus → normal discovery |
| 7 | Create seeding status API | Integration test: status endpoint returns correct state |
| 8 | Run evaluation | T53.1: seeded clustering purity exceeds unseeded baseline |

**Atomic Sub-tasks:**
1. Centroid seeding service (syllabus embeddings → initial centroids)
2. Session 1 clustering integration with seeded centroids
3. Re-cluster cadence logic (tight: sessions 2–5; normal: session 6+)
4. Seed replacement logic (observed data replaces initial seeds)
5. Post-session hook wiring for automatic re-clustering
6. No-syllabus path (graceful opt-out)
7. Seeding status API
8. Evaluation harness for cold-start improvement

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| No syllabus exists for subject | Seeding skipped, normal discovery, no error |
| Syllabus uploaded after session 1 | Seeding NOT applied retroactively, logged as "too late for cold start" |
| Syllabus has 0 items | Seeding skipped, logged as "empty syllabus" |
| Syllabus embeddings dimension mismatch | Error logged, seeding skipped, normal discovery continues |
| All seed centroids replaced by data | Status → STABILIZED, normal cadence from next session |
| Session 1 has no audio/transcript | Clustering skipped, seeding preserved for session 2 |
| Re-clustering produces fewer clusters than seeds | Merge closest seeds, log warning |
| Re-clustering produces more clusters than seeds | New clusters added, seeds retained for unmatched clusters |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: seeded vs. unseeded clustering initialization
- Observer pattern: session hooks trigger re-clustering
- State machine: seeding status transitions
- Factory pattern: `create_seed_service()` for dependency injection

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`CentroidSeedService`, `ReclusterService`)
- Files: snake_case (`seed.py`, `recluster.py`, `session_hooks.py`)
- Constants: UPPER_SNAKE_CASE (`TIGHT_CADENCE_SESSIONS = 5`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- Enum types for seeding status and cadence

---

### 5. API & Interface Contracts

**Centroid Seeding Service:**
```python
# src/services/clustering/seed.py
class CentroidSeedService:
    async def get_seeds(self, subject_id: UUID) -> list[CentroidSeed]:
        """Get initial centroid seeds from syllabus item embeddings.
        
        Returns empty list if no syllabus exists.
        """
        ...

    async def create_seeds(self, subject_id: UUID) -> SeedingResult:
        """Create initial centroid seeds from syllabus items.
        
        1. Read syllabus items from DB-3 (via FDW)
        2. Extract embeddings for each item
        3. Return as CentroidSeed list with syllabus_item_id mapping
        """
        ...

    async def check_seed_status(self, subject_id: UUID) -> SeedingResult:
        """Check current seeding status and how many seeds remain."""
        ...

    async def replace_seed(
        self, subject_id: UUID, seed_id: UUID, replacement_embedding: list[float]
    ) -> CentroidSeed:
        """Replace a seed centroid with observed session data."""
        ...
```

**Re-Cluster Service:**
```python
# src/services/clustering/recluster.py
class ReclusterService:
    async def should_recluster(
        self, subject_id: UUID, session_number: int
    ) -> bool:
        """Determine if re-clustering should run for this session.
        
        Session 1: no re-cluster (initial seeded clustering)
        Sessions 2–5: always re-cluster (tight cadence)
        Session 6+: re-cluster every N sessions (normal cadence)
        """
        ...

    async def recluster(
        self, subject_id: UUID, new_topics: list[UUID]
    ) -> list[ClusterResult]:
        """Re-cluster topics for a subject.
        
        1. Get all topics (including new ones from this session)
        2. Get seed centroids (if still active)
        3. Run clustering with combined seeds + observed data
        4. Update seed status (replace seeds that match observed clusters)
        5. Return updated cluster assignments
        """
        ...

    async def replace_seeds_from_clusters(
        self, subject_id: UUID, clusters: list[ClusterResult]
    ) -> int:
        """Replace seed centroids that are now covered by real cluster centers.
        
        Returns number of seeds replaced.
        """
        ...
```

**Session Hook Integration:**
```python
# src/graph/session_hooks.py
async def on_session_complete(session_id: UUID, subject_id: UUID) -> None:
    """Post-session hook: triggers coverage update (S52) and re-clustering (S53)."""
    session_number = await get_session_number(subject_id)
    
    # Coverage update (S52)
    await coverage_service.post_session_update(subject_id, session_id)
    
    # Re-clustering (S53) — only if seeding is active
    if await recluster_service.should_recluster(subject_id, session_number):
        new_topics = await get_new_topics(session_id)
        await recluster_service.recluster(subject_id, new_topics)
```

**Seeding Status API:**
```yaml
# GET /api/v1/subjects/{subject_id}/cold-start/status
/api/v1/subjects/{subject_id}/cold-start/status:
  get:
    summary: Check syllabus seeding status for cold start
    responses:
      200:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SeedingResult'
```

**Mock Request/Response:**
```json
// GET /api/v1/subjects/550e8400-e29b-41d4-a716-446655440000/cold-start/status

// Response (syllabus exists, session 3 in progress)
{
  "subject_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "seeded",
  "seed_count": 15,
  "seeds": [
    {
      "syllabus_item_id": "...",
      "title": "Module 1: Introduction",
      "initial_topic_id": "...",
      "replaced_by_data": false
    }
  ],
  "session_count": 3,
  "recluster_cadence": "tight"
}

// Response (no syllabus)
{
  "subject_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "not_seeded",
  "seed_count": 0,
  "seeds": [],
  "session_count": 3,
  "recluster_cadence": "normal"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `SEEDING_ENABLED` | bool | Feature flag for syllabus seeding | `true` |
| `SEED_TIGHT_CADENCE_SESSIONS` | int | Number of sessions with tight re-cluster cadence | `5` |
| `SEED_REPLACEMENT_THRESHOLD` | float | Cosine similarity to replace seed with observed data | `0.70` |
| `SEED_NORMAL_CADENCE_INTERVAL` | int | Re-cluster every N sessions after tight cadence | `5` |
| `SEED_MIN_TOPICS_FOR_RECLUSTER` | int | Minimum topics to trigger re-clustering | `3` |
| `CLUSTERING_ALGORITHM` | string | Clustering algorithm (kmeans/hdbscan) | `hdbscan` |

**Third-Party Integration Contracts:**
- scikit-learn: KMeans (with `init` parameter for seed centroids) or HDBSCAN (with `cluster_selection_epsilon`)
- pgvector: cosine distance queries for seed replacement checks
- S11 FDW link: read syllabus items from PG-MAIN
- S50 A6 extraction: source of syllabus items and embeddings
- S28–S32 topic discovery: source of observed topic data for clustering
- S52 coverage: post-session hook shared with coverage recomputation

**Version Pins:**
- scikit-learn pinned in `pyproject.toml`
- NumPy pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T53.1 | V | `pytest tests/test_syllabus_seed.py::test_seeded_purity_exceeds_baseline -v` | First-session clustering purity with seeding materially exceeds unseeded baseline |
| T53.2 | I | `pytest tests/test_syllabus_seed.py::test_seeds_replaced_by_data -v` | Seeded centroids are replaced by observed data as sessions accumulate |
| T53.3 | I | `pytest tests/test_syllabus_seed.py::test_no_syllabus_path -v` | No-syllabus path still works (seeding is optional) |
| T53.4 | I | `pytest tests/test_early_session_recluster.py::test_sessions_2_5_recluster -v` | Sessions 2–5 trigger re-clustering per tight cadence |

**Test Case Details (Given/When/Then):**

**T53.1 — Seeded clustering purity exceeds unseeded baseline**
- **Given:** a subject with a syllabus of 10 modules and 30 topics, with labelled ground truth clusters
- **When:** session 1 is processed with seeded centroids (from syllabus item embeddings)
- **Then:** clustering purity (e.g., normalized mutual information or purity score) with seeding is ≥ 0.10 higher than the same session processed without seeding (unseeded baseline)

**T53.2 — Seeds replaced by observed data**
- **Given:** a seeded subject with 15 centroid seeds, after 5 sessions with 20+ discovered topics
- **When:** `replace_seeds_from_clusters()` runs
- **Then:** at least 5 of the 15 seeds are marked as `replaced_by_data=True`; replacement happens when a real cluster center has cosine similarity > 0.70 to the seed

**T53.3 — No-syllabus path works**
- **Given:** a subject with NO syllabus uploaded
- **When:** sessions 1–5 are processed
- **Then:** no seeding occurs, topic discovery proceeds normally via S28–S32; no errors, no seeding-related log entries; `GET /cold-start/status` returns `status: "not_seeded"`

**T53.4 — Sessions 2–5 trigger re-clustering**
- **Given:** a seeded subject at session 2 with 5 new topics from the session
- **When:** session completes and `on_session_complete` hook fires
- **Then:** `ReclusterService.should_recluster()` returns True for sessions 2, 3, 4, 5; re-clustering runs and produces updated cluster assignments; session 6 uses normal cadence (does NOT re-cluster unless interval met)

**Verification Commands:**
```bash
# Full local verification
uv run pytest tests/test_syllabus_seed.py tests/test_early_session_recluster.py -v -k "S53 or seed or cold_start" && \
uv run mypy --strict src/services/clustering/seed.py src/services/clustering/recluster.py && \
uv run ruff check src/services/clustering/seed.py src/services/clustering/recluster.py && \
uv run pytest tests/test_syllabus_seed.py::test_seeded_purity_exceeds_baseline -v  # eval gate
```

**Exit Criteria:**
- [ ] T53.1 passes — seeded clustering purity materially exceeds unseeded baseline
- [ ] T53.2 passes — seeds replaced by observed data as sessions accumulate
- [ ] T53.3 passes — no-syllabus path still works (seeding optional)
- [ ] T53.4 passes — sessions 2–5 trigger re-clustering per tight cadence

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- KMeans `init` parameter accepts pre-computed centroids — ensure centroid matrix shape matches `n_clusters`
- HDBSCAN does not accept pre-defined centroids directly — use `cluster_selection_epsilon` tuned to syllabus granularity instead, or use KMeans for seeded sessions and switch to HDBBSDAN later
- Seed replacement threshold must be tuned per embedding model — 0.70 works for general-purpose embeddings but may need adjustment for domain-adapted models (S67)
- Tight re-cluster cadence (sessions 2–5) may be expensive for large topic counts — set `min_topics_for_recluster` to avoid re-clustering with too few topics
- Syllabus uploaded AFTER session 1 cannot seed — the cold-start window is only before the first session

**Fallback Instructions:**
- If seeding fails (e.g., embedding dimension mismatch): log error, skip seeding, proceed with normal discovery
- If re-clustering is too slow (> 30s): skip re-cluster for this session, flag for next session
- If seed replacement produces too many replacements in one session (> 50%): log warning, limit replacements to 50% per session
- If no syllabus exists: seeding is completely skipped, no impact on existing flow

**Rollback Procedure:**
- Disable seeding: set `SEEDING_ENABLED=false` in `.env`
- All sessions use normal (unseeded) clustering from that point
- Existing seeded centroids remain in DB but are ignored
- To fully clear seeding state: `DELETE FROM centroid_seeds WHERE subject_id = '<id>'`
- Tight cadence for sessions 2–5 is also disabled when seeding is off
- No database migration rollback needed — seeding state is additive

---

### 9. Observability

**Metrics Added:**
- `cold_start_seeding_total`: counter of seeding events (labels: status=seeded/not_seeded/error)
- `cold_start_seed_count`: gauge of active seeds per subject
- `cold_start_seeds_replaced_total`: counter of seed replacements (per session)
- `cold_start_recluster_total`: counter of re-cluster triggers (labels: cadence=tight/normal)
- `cold_start_recluster_duration_seconds`: histogram of re-clustering latency
- `cold_start_purity_score`: gauge of clustering purity (for eval tracking)

**Tracing/Logging:**
- Span: `cold_start.seed` with attributes (subject_id, seed_count, syllabus_item_count)
- Span: `cold_start.recluster` with attributes (subject_id, session_number, cadence, topic_count, latency_ms)
- Span: `cold_start.replace_seeds` with attributes (replaced_count, remaining_count)
- Log: INFO on seeding completion with seed count
- Log: INFO on seed replacement with similarity scores
- Log: INFO on re-cluster completion with cluster count
- Log: WARNING when re-clustering skipped (too few topics)

**Alerts:**
- Seeding failure rate > 10% over 1 day: investigate embedding model or DB-3 availability
- Re-clustering P95 > 30s: check topic count growth, consider optimization
- Purity score drops below 0.60 over 1 week: investigate embedding model drift or syllabus quality

---

### 10. Exit Checklist

- [ ] All tests pass (T53.1, T53.2, T53.3, T53.4)
- [ ] Seeded clustering purity materially exceeds unseeded baseline
- [ ] Seed centroids are replaced by observed data as sessions accumulate
- [ ] No-syllabus path works without errors
- [ ] Sessions 2–5 trigger re-clustering per tight cadence
- [ ] Session 6+ uses normal cadence
- [ ] Feature flag `SEEDING_ENABLED` disables seeding gracefully
- [ ] Observability: metrics, traces, and alerts in place
- [ ] Cold-start weakness measurably reduced when syllabus is available

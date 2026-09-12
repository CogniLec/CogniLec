# S28 — Boundary Detection (Segmentation)
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement custom TextTiling-style sequential segmentation over windowed embeddings: adjacent-block cosine similarity with an adaptively determined threshold, producing ordered, contiguous, non-overlapping segments with boundary scores.

**Component Boundaries:**
- **Allowed:** `src/ml/segmentation/`, `src/services/segmentation.py`, `src/db/repositories/segment_repo.py`, `tests/test_segmentation.py`
- **Off-limits:** Embedding generation (S25-S26), clustering (S30), evaluation (S29)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| numpy | 1.26.x | Cosine similarity computation |
| scipy | 1.13.x | Signal processing for depth scores |
| scikit-learn | 1.5.1 | Cosine similarity metrics |
| pytest | 8.x | Unit and integration tests |
| hypothesis | 6.x | Property-based testing |

---

### 2. State Machine & Domain Schemas

**Segmentation Algorithm State:**
```
Input: ordered list of windowed embeddings
  ↓
Compute pairwise cosine similarity between adjacent blocks
  ↓
Compute depth scores (similarity drop from local peaks)
  ↓
Determine adaptive threshold (mean - k * std of depth scores)
  ↓
Identify boundary positions where depth > threshold
  ↓
Output: ordered, contiguous, non-overlapping segments
```

**Pydantic Models:**
```python
# src/ml/segmentation/models.py
from pydantic import BaseModel, Field

class SegmentationConfig(BaseModel):
    block_size: int = Field(default=1, ge=1, description="Number of utterances per block for similarity")
    threshold_factor: float = Field(default=1.0, ge=0.1, le=5.0, description="k in mean - k*std adaptive threshold")
    min_segment_size: int = Field(default=3, ge=1, description="Minimum utterances per segment")
    similarity_metric: str = "cosine"

class BoundaryCandidate(BaseModel):
    position: int  # Index between utterances (0 = before first utterance)
    depth_score: float  # Magnature of similarity drop
    is_boundary: bool  # True if depth > threshold

class SegmentationResult(BaseModel):
    session_id: UUID
    segments: list[SegmentOutput]
    boundary_scores: list[BoundaryCandidate]
    threshold_used: float
    num_segments: int

class SegmentOutput(BaseModel):
    start_utt_idx: int  # 0-indexed position in session
    end_utt_idx: int
    start_utt_id: UUID
    end_utt_id: UUID
    utterance_count: int
    boundary_score: float | None = None  # Score at segment start boundary
    confidence: float | None = None
```

**Segment Properties (invariants):**
```
1. Segments are contiguous: segment[i].end_utt_idx + 1 == segment[i+1].start_utt_idx
2. Segments are ordered: segment[i] starts before segment[i+1]
3. Segments are non-overlapping: no utterance belongs to two segments
4. Every utterance belongs to exactly one segment
5. Segment boundaries align with depth score peaks
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Implement cosine similarity computation between adjacent blocks | Similarity values in [-1, 1] |
| 2 | Implement depth score computation | Depth scores are non-negative |
| 3 | Implement adaptive threshold determination | Threshold = mean(depth) - k * std(depth) |
| 4 | Implement boundary detection | T28.1, T28.2 pass |
| 5 | Implement segment construction from boundaries | Segments are contiguous and non-overlapping |
| 6 | Persist segments to `segments` table | T28.1, T28.2 pass |
| 7 | Run synthetic transcript test | T28.3, T28.4 pass |
| 8 | Run performance benchmark | T28.5 passes |

**Atomic Sub-tasks:**
1. Adjacent-block cosine similarity computation
2. Depth score computation (TextTiling-style)
3. Adaptive threshold determination
4. Boundary detection from depth scores
5. Segment construction with contiguous/non-overlapping guarantees
6. Segment persistence to DB with boundary scores
7. Hypothesis property tests for structural invariants

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Single utterance session | One segment covering the entire session |
| All utterances very similar | One segment (no boundaries detected) |
| All utterances very different | Many small segments, enforced by `min_segment_size` |
| `min_segment_size` too large | Merge adjacent small segments until constraint met |
| Empty embedding list | Return empty segmentation result |
| Boundary at position 0 or N | Ignore; segments must contain at least one utterance |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: pluggable similarity metrics
- Builder pattern: `SegmentBuilder` constructs segments from boundaries
- Repository pattern: `SegmentRepository` for DB operations

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`segmenter.py`, `depth_scores.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**Segmentation Interface:**
```python
# src/ml/segmentation/segmenter.py
class TextTilingSegmenter:
    def __init__(self, config: SegmentationConfig):
        self.config = config

    def segment(
        self,
        utterance_ids: list[UUID],
        embeddings: list[list[float]],
    ) -> SegmentationResult:
        """
        Segment a session into topic segments.

        Args:
            utterance_ids: Ordered list of utterance UUIDs
            embeddings: Corresponding windowed embeddings (same order)

        Returns:
            SegmentationResult with segments, boundary scores, and threshold
        """
        # 1. Compute adjacency similarities
        similarities = self._compute_similarities(embeddings)

        # 2. Compute depth scores
        depths = self._compute_depth_scores(similarities)

        # 3. Determine adaptive threshold
        threshold = self._compute_threshold(depths)

        # 4. Detect boundaries
        boundaries = self._detect_boundaries(depths, threshold)

        # 5. Construct segments
        segments = self._construct_segments(
            utterance_ids, boundaries, embeddings
        )

        return SegmentationResult(
            session_id=session_id,
            segments=segments,
            boundary_scores=boundaries,
            threshold_used=threshold,
            num_segments=len(segments),
        )

    def _compute_similarities(
        self, embeddings: list[list[float]]
    ) -> list[float]:
        """Compute cosine similarity between adjacent blocks."""
        sims = []
        for i in range(len(embeddings) - 1):
            sim = cosine_similarity(
                [embeddings[i]], [embeddings[i + 1]]
            )[0][0]
            sims.append(float(sim))
        return sims

    def _compute_depth_scores(
        self, similarities: list[float]
    ) -> list[float]:
        """
        TextTiling depth score: the drop from the local similarity peak.
        depth[i] = peak_left - similarity[i] if similarity[i] is a local valley
        """
        depths = [0.0] * len(similarities)
        for i in range(1, len(similarities) - 1):
            left_peak = max(similarities[max(0, i - 2):i])
            right_peak = max(similarities[i + 1:min(len(similarities), i + 3)])
            peak = max(left_peak, right_peak)
            depth = peak - similarities[i]
            depths[i] = max(0.0, depth)
        return depths

    def _compute_threshold(self, depths: list[float]) -> float:
        """Adaptive threshold: mean - k * std of depth scores."""
        import numpy as np
        arr = np.array(depths)
        threshold = float(arr.mean() - self.config.threshold_factor * arr.std())
        return max(0.0, threshold)

    def _detect_boundaries(
        self, depths: list[float], threshold: float
    ) -> list[BoundaryCandidate]:
        """Identify positions where depth > threshold."""
        candidates = []
        for i, depth in enumerate(depths):
            candidates.append(BoundaryCandidate(
                position=i + 1,  # Boundary after utterance i
                depth_score=depth,
                is_boundary=depth > threshold,
            ))
        return candidates

    def _construct_segments(
        self,
        utterance_ids: list[UUID],
        boundaries: list[BoundaryCandidate],
        embeddings: list[list[float]],
    ) -> list[SegmentOutput]:
        """Build contiguous, non-overlapping segments from boundaries."""
        boundary_positions = [
            b.position for b in boundaries if b.is_boundary
        ]
        # Add implicit boundaries at start and end
        all_boundaries = [0] + boundary_positions + [len(utterance_ids)]

        segments = []
        for i in range(len(all_boundaries) - 1):
            start = all_boundaries[i]
            end = all_boundaries[i + 1]
            if end - start < self.config.min_segment_size:
                continue  # Skip segments smaller than minimum

            # Find boundary score at segment start
            bscore = None
            for b in boundaries:
                if b.position == start and b.is_boundary:
                    bscore = b.depth_score
                    break

            segments.append(SegmentOutput(
                start_utt_idx=start,
                end_utt_idx=end - 1,
                start_utt_id=utterance_ids[start],
                end_utt_id=utterance_ids[end - 1],
                utterance_count=end - start,
                boundary_score=bscore,
            ))

        return segments
```

**Service Interface:**
```python
# src/services/segmentation.py
class SegmentationService:
    async def segment_session(
        self,
        subject_id: UUID,
        session_id: UUID,
    ) -> SegmentationResult:
        """Segment all utterances in a session and persist to DB."""
        utterances = await utterance_repo.get_by_session(subject_id, session_id)
        embeddings = [u.embedding for u in utterances]
        utterance_ids = [u.id for u in utterances]

        result = self.segmenter.segment(utterance_ids, embeddings)

        # Persist segments
        segment_creates = [
            SegmentCreate(
                subject_id=subject_id,
                session_id=session_id,
                start_utt=s.start_utt_id,
                end_utt=s.end_utt_id,
                boundary_score=s.boundary_score,
                confidence=s.confidence,
            )
            for s in result.segments
        ]
        await segment_repo.bulk_insert(subject_id, segment_creates)

        return result
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `SEGMENTATION_BLOCK_SIZE` | int | Block size for similarity | `1` |
| `SEGMENTATION_THRESHOLD_FACTOR` | float | k in adaptive threshold | `1.0` |
| `SEGMENTATION_MIN_SEGMENT_SIZE` | int | Minimum utterances per segment | `3` |

**Third-Party Integration Contracts:**
- scipy: cosine similarity and signal processing
- numpy: array operations for depth scores
- pgvector: embedding storage from S09

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T28.1 | U | `pytest tests/test_segmentation.py::test_segments_contiguous_nonoverlapping -v` | Segments are contiguous, ordered and non-overlapping (Hypothesis) |
| T28.2 | U | `pytest tests/test_segmentation.py::test_every_utterance_in_one_segment -v` | Every utterance belongs to exactly one segment |
| T28.3 | V | `pytest tests/test_segmentation.py::test_synthetic_boundary_recovery -v` | On synthetic transcripts, boundaries recovered within ±2 utterances |
| T28.4 | V | `pytest tests/test_segmentation.py::test_single_topic_yields_one_segment -v` | Single-topic lecture yields one segment |
| T28.5 | P | `pytest tests/test_segmentation.py::test_segmentation_performance -v` | 1,000 utterances segmented in < 10s |

**Test Case Details (Given/When/Then):**

**T28.1 — Structural invariants (Hypothesis property test)**
- **Given:** a random transcript of 50-200 utterances with random embeddings
- **When:** segmentation is run
- **Then:** segments are contiguous (end[i]+1 == start[i+1]), ordered (start[i] < start[i+1]), and non-overlapping (no shared utterance IDs)

**T28.2 — Every utterance in exactly one segment**
- **Given:** any transcript with embeddings
- **When:** segmentation is run and utterance membership is checked
- **Then:** the union of all segment utterance sets equals the full utterance set; intersection of any two segments is empty

**T28.3 — Synthetic boundary recovery**
- **Given:** a synthetic transcript with known topic boundaries at positions [15, 35] (from S13 generator)
- **When:** segmentation is run
- **Then:** detected boundaries are within ±2 utterances of the ground truth boundaries

**T28.4 — Single topic yields one segment**
- **Given:** a transcript covering a single topic (all utterances about photosynthesis)
- **When:** segmentation is run
- **Then:** exactly one segment is produced; no spurious splits

**T28.5 — Segmentation performance**
- **Given:** 1,000 utterances with pre-computed embeddings
- **When:** segmentation is run
- **Then:** completes in under 10 seconds

**Verification Commands:**
```bash
uv run pytest tests/test_segmentation.py -v && \
uv run mypy --strict src/ml/segmentation/ && \
uv run ruff check src/ml/segmentation/
```

**Exit Criteria:**
- [ ] T28.1 passes — segments are contiguous, ordered, non-overlapping
- [ ] T28.2 passes — every utterance in exactly one segment
- [ ] T28.3 passes — synthetic boundaries recovered within ±2 utterances
- [ ] T28.4 passes — single topic yields one segment
- [ ] T28.5 passes — 1,000 utterances in < 10s
- [ ] Segmentation produces structurally valid, ordered segments on both synthetic and real transcripts

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Depth score at the first and last position is always 0 (no left/right peak) — must handle boundary conditions
- `min_segment_size` too small produces over-segmentation; too large merges distinct topics
- Adaptive threshold with `threshold_factor=1.0` may be too aggressive on noisy data — tune per S09
- Cosine similarity of zero vectors is undefined — filter out zero embeddings before segmentation

**Fallback Instructions:**
- If segmentation produces too many segments: increase `threshold_factor` or `min_segment_size`
- If segmentation produces too few segments: decrease `threshold_factor`
- If boundary recovery on synthetic fails: check depth score computation against TextTiling paper

**Rollback Procedure:**
- Delete segments for affected session: `DELETE FROM segments WHERE session_id = $1`
- Re-segment with different config
- No schema migration rollback needed

---

### 9. Observability (if applicable)

**Metrics Added:**
- `segmentation_session_total`: counter of segmentation runs
- `segmentation_segments_per_session`: histogram of segments per session
- `segmentation_boundary_scores`: histogram of depth scores
- `segmentation_duration_seconds`: histogram of segmentation time
- `segmentation_threshold_used`: gauge of adaptive threshold per session

**Tracing/Logging:**
- Span: `segmentation.segment_session` with attributes (session_id, utterance_count, segment_count, threshold)
- Log: INFO on segmentation completion with summary
- Log: WARN on edge cases (single segment, many small segments)

**Alerts:**
- Average segments per session < 1.5: threshold may be too high
- Segmentation time > 30s for < 1000 utterances: performance regression

---

### 10. Exit Checklist

- [ ] All tests pass (T28.1, T28.2, T28.3, T28.4, T28.5)
- [ ] Segments are contiguous, ordered, non-overlapping
- [ ] Every utterance belongs to exactly one segment
- [ ] Synthetic boundaries recovered within ±2 utterances
- [ ] Single-topic transcripts yield one segment
- [ ] Performance < 10s for 1,000 utterances
- [ ] Boundary scores persisted in `segments` table

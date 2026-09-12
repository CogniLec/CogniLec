# S26 — Context-Window Embedding
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Embed overlapping windows of W preceding utterances plus the current one instead of isolated utterances, because single ASR utterances are too sparse and noisy to embed meaningfully.

**Component Boundaries:**
- **Allowed:** `src/services/embedding/windowing.py`, `config/embedding.yaml`, `tests/test_windowing.py`
- **Off-limits:** Embedding service deployment (S25), segmentation (S28), clustering (S30)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| numpy | 1.26.x | Window mean-pooling |
| sentence-transformers | 3.2.x | Embedding client |
| pytest | 8.x | Unit tests |
| segeval | 0.1.2 | Purity comparison benchmark |

---

### 2. State Machine & Domain Schemas

**Windowing Configuration:**
```yaml
# config/embedding.yaml
windowing:
  W: 5                    # Number of preceding utterances in window
  min_window_size: 1      # Minimum utterances in window (at transcript start)
  overlap: true           # Overlapping windows (sliding)
  pool_strategy: "mean"   # How to combine window embeddings
```

**Pydantic Models:**
```python
# src/services/embedding/windowing.py
from pydantic import BaseModel, Field

class WindowConfig(BaseModel):
    W: int = Field(default=5, ge=0, description="Number of preceding utterances in context window")
    min_window_size: int = Field(default=1, ge=1)
    overlap: bool = True
    pool_strategy: str = "mean"

class WindowedUtterance(BaseModel):
    utterance_id: UUID
    seq: int
    text: str
    window_texts: list[str]  # [utt_{i-W}, ..., utt_{i-1}, utt_i]
    window_size: int         # Actual size (may be < W at transcript start)
    embedding: list[float] | None = None
```

**Window Construction Rules:**
```
For utterance at position i in session:
  window_start = max(0, i - W)
  window_end = i
  window_texts = transcript[window_start : window_end + 1]
  window_size = len(window_texts)

At transcript start (i < W):
  window = [utt_0, ..., utt_i]  (fewer than W predecessors)

At transcript end (i near N):
  window = [utt_{i-W}, ..., utt_i]  (full W predecessors)

W=0 degenerates to isolated embedding:
  window = [utt_i]
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `WindowConfig` in `config/embedding.yaml` | Config loads without error |
| 2 | Implement `WindowBuilder` class with configurable W | T26.1, T26.3 pass |
| 3 | Integrate windowing into embedding pipeline | Windowed embeddings produced |
| 4 | Implement mean-pooling of window embeddings | Pool produces single vector per utterance |
| 5 | Run comparative benchmark: windowed vs isolated | T26.2 passes |
| 6 | Run performance benchmark | T26.4 passes |

**Atomic Sub-tasks:**
1. `WindowConfig` Pydantic model and YAML loading
2. `WindowBuilder.build_windows(session_transcript, W)` — produces `list[WindowedUtterance]`
3. Mean-pooling strategy for combining window embeddings
4. Integration with `EmbeddingClient` from S25
5. Comparative benchmark against S05 ground truth labels

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Session has < W utterances | Use `min(available, W)` predecessors; window is smaller |
| W=0 configured | Degenerate to isolated embedding (no window context) |
| Window contains empty utterances | Filter empty texts before pooling |
| Mean-pooling produces NaN | Check for empty arrays; return zero vector |
| Window memory exceeds limit | Limit W; log warning if window size > threshold |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Builder pattern: `WindowBuilder` constructs windows from transcript
- Strategy pattern: `pool_strategy` selects mean/median pooling
- Config pattern: `WindowConfig` Pydantic model from YAML

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`windowing.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**WindowBuilder Interface:**
```python
# src/services/embedding/windowing.py
class WindowBuilder:
    def __init__(self, config: WindowConfig):
        self.config = config

    def build_windows(
        self, utterances: list[UtteranceCreate]
    ) -> list[WindowedUtterance]:
        """
        Build context windows for each utterance.
        utterances must be ordered by seq.
        Returns one WindowedUtterance per input.
        """
        windows = []
        for i, utt in enumerate(utterances):
            start = max(0, i - self.config.W)
            window_texts = [u.text for u in utterances[start:i + 1]]
            windows.append(WindowedUtterance(
                utterance_id=utt.id,
                seq=utt.seq,
                text=utt.text,
                window_texts=window_texts,
                window_size=len(window_texts),
            ))
        return windows

    def pool_embeddings(
        self, window_embeddings: list[list[float]]
    ) -> list[float]:
        """
        Mean-pool a list of per-window embeddings into a single vector.
        """
        import numpy as np
        arr = np.array(window_embeddings)
        return np.mean(arr, axis=0).tolist()
```

**Windowed Embedding Pipeline:**
```python
# src/services/embedding/pipeline.py
class WindowedEmbeddingPipeline:
    def __init__(
        self,
        client: EmbeddingClient,
        window_builder: WindowBuilder,
    ):
        self.client = client
        self.window_builder = window_builder

    async def embed_session(
        self,
        utterances: list[UtteranceCreate],
        task_mode: EmbeddingTaskMode = EmbeddingTaskMode.RETRIEVAL,
    ) -> list[WindowedUtterance]:
        """Embed all utterances in a session using context windows."""
        windows = self.window_builder.build_windows(utterances)

        # Batch embed all window texts
        all_texts = [w.window_texts for w in windows]
        # Each window is embedded as a concatenated string
        concatenated = [" ".join(texts) for texts in all_texts]
        embeddings = await self.client.embed(concatenated, task_mode)

        for window, emb in zip(windows, embeddings):
            window.embedding = emb

        return windows
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `EMBEDDING_WINDOW_W` | int | Context window size | `5` |
| `EMBEDDING_POOL_STRATEGY` | string | Pooling strategy | `mean` |

**Config File:**
```yaml
# config/embedding.yaml
windowing:
  W: 5
  min_window_size: 1
  overlap: true
  pool_strategy: "mean"
```

**Third-Party Integration Contracts:**
- EmbeddingClient from S25 for actual vector generation
- numpy for mean-pooling computation

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T26.1 | U | `pytest tests/test_windowing.py::test_window_construction -v` | Window construction correct at transcript start and end |
| T26.2 | V | `pytest tests/test_windowing.py::test_windowed_purity -v` | Windowed embeddings produce higher clustering purity than isolated |
| T26.3 | U | `pytest tests/test_windowing.py::test_w_configurable -v` | W is configurable; W=0 degenerates to isolated embedding |
| T26.4 | P | `pytest tests/test_windowing.py::test_windowing_overhead -v` | Windowing adds < 20% to embedding time |

**Test Case Details (Given/When/Then):**

**T26.1 — Window construction at transcript boundaries**
- **Given:** a session transcript with 20 utterances and W=5
- **When:** windows are built for utterances at position 0, 2, 10, 19
- **Then:** utterance 0 has window [utt_0] (size 1); utterance 2 has [utt_0..utt_2] (size 3); utterances 10 and 19 have full windows of size 6

**T26.2 — Windowed embedding outperforms isolated**
- **Given:** S05 labelled transcripts with known topic boundaries
- **When:** utterances are embedded both with W=5 (windowed) and W=0 (isolated)
- **Then:** windowed embeddings achieve higher purity when clustered; purity difference > 0.05

**T26.3 — W is configurable, W=0 degenerates**
- **Given:** a session transcript and WindowConfig with W=0
- **When:** windows are built
- **Then:** each window contains exactly 1 utterance (the utterance itself); embedding is identical to isolated embedding

**T26.4 — Windowing overhead < 20%**
- **Given:** 1,000 utterances and an embedding client
- **When:** embedding is run with W=5 (windowed) and W=0 (isolated)
- **Then:** wall-clock time for windowed is < 1.2x isolated time

**Verification Commands:**
```bash
uv run pytest tests/test_windowing.py -v && \
uv run mypy --strict src/services/embedding/windowing.py && \
uv run ruff check src/services/embedding/windowing.py
```

**Exit Criteria:**
- [ ] T26.1 passes — window construction correct at boundaries
- [ ] T26.2 passes — windowed embeddings measurably outperform isolated
- [ ] T26.3 passes — W configurable, W=0 degenerates
- [ ] T26.4 passes — windowing overhead < 20%
- [ ] Windowed embedding measurably outperforms naive embedding
- [ ] W chosen on evidence from S05 labels

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Window concatenation without instruction prefix loses task-mode differentiation — must prepend prefix to concatenated text
- Very large W causes OOM in batch embedding — cap W at 10, log warning
- Mean-pooling over semantically diverse windows dilutes the embedding — W too large reduces purity
- At transcript start, small windows may produce noisy embeddings — expected, not an error

**Fallback Instructions:**
- If windowed purity < isolated purity: reduce W; the context may be too noisy
- If pooling produces NaN: check for empty window_texts; filter before pooling

**Rollback Procedure:**
- Set `W=0` in `config/embedding.yaml` to disable windowing
- Re-embed session with isolated mode
- No schema changes to revert

---

### 9. Observability (if applicable)

**Metrics Added:**
- `embedding_window_size`: histogram of actual window sizes per utterance
- `embedding_window_overhead_ratio`: gauge of windowed vs isolated time ratio
- `embedding_window_purity_comparison`: gauge comparing windowed vs isolated purity

**Tracing/Logging:**
- Span: `embedding.window.build` with attributes (utterance_count, W, avg_window_size)
- Log: INFO on window configuration changes
- Log: WARN if window size < expected at non-boundary positions

**Alerts:**
- Window overhead > 30%: investigate batching or W configuration
- Purity regression vs isolated: W may be too large

---

### 10. Exit Checklist

- [ ] All tests pass (T26.1, T26.2, T26.3, T26.4)
- [ ] Window construction handles transcript start/end correctly
- [ ] W is configurable via `config/embedding.yaml`
- [ ] W=0 degenerates to isolated embedding
- [ ] Windowed embeddings outperform isolated on S05 labels
- [ ] Windowing overhead < 20%
- [ ] W value chosen based on S05 evidence

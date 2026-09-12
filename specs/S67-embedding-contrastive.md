# S67 — Embedding Contrastive Fine-Tune
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Contrastively fine-tune the embedding model on accumulated lecture data to improve clustering purity, cross-session topic matching, and retrieval precision, with safe staged rollout and rollback path.

**Component Boundaries:**
- **Allowed:** `src/models/embedding_finetune/`, `src/training/contrastive/`, `src/serving/embeddings/`, `config/models.yaml`, `tests/`
- **Off-limits:** ASR models (S68), A1 classifier (S66), LoRA adapters (S69), core schema (S07)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12.x | Runtime |
| PyTorch | 2.3.x | ML framework |
| sentence-transformers | 3.x | Contrastive training |
| faiss-gpu | 1.8.x | Hard negative mining |
| DVC | 3.x | Dataset versioning |
| NumPy | 1.26.x | Array operations |

---

### 2. State Machine & Domain Schemas

**Training Pipeline State:**
```
data_preparation → hard_negative_mining → contrastive_training → evaluation → staged_rollout
```

**Pydantic Schemas:**

```python
# src/api/schemas/embedding_finetune.py
class ContrastiveConfig(BaseModel):
    base_model: str = "BAAI/bge-base-en-v1.5"
    training_data_version: str
    hard_negative_samples: int = 10000
    positive_pairs_per_utterance: int = 5
    negative_pairs_per_utterance: int = 10
    learning_rate: float = 2e-5
    num_epochs: int = 3
    batch_size: int = 64
    temperature: float = 0.07
    warmup_ratio: float = 0.1

class ContrastiveResult(BaseModel):
    model_version: str
    clustering_purity: float
    cross_session_accuracy: float
    retrieval_precision_at_5: float
    hard_negatives_mined: int
    training_samples: int
    created_at: datetime

class BackfillConfig(BaseModel):
    model_version: str
    subject_id: UUID
    batch_size: int = 1000
    resumable: bool = True
```

**SQLAlchemy Models:**

```python
# src/db/models/embedding_version.py
class EmbeddingVersion(Base):
    __tablename__ = "embedding_versions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    version: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    base_model: Mapped[str] = mapped_column(String(255), nullable=False)
    training_data_version: Mapped[str] = mapped_column(String(50), nullable=False)
    clustering_purity: Mapped[float] = mapped_column(Float, nullable=False)
    cross_session_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    retrieval_precision_at_5: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class EmbeddingBackfill(Base):
    __tablename__ = "embedding_backfills"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/running/complete/failed
    processed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create Alembic migration for `embedding_versions` and `embedding_backfills` tables | `alembic upgrade head` succeeds |
| 2 | Prepare training data: same-topic utterance pairs as positives | Positive pairs generated |
| 3 | Mine hard negatives using faiss-gpu over full corpus | Hard negatives confirmed different-topic |
| 4 | Train contrastive model with sentence-transformers | Training completes; model saved |
| 5 | Evaluate clustering purity on S05 labels | T67.1 passes |
| 6 | Evaluate cross-session topic matching (S32 T32.1) | T67.2 passes |
| 7 | Evaluate retrieval precision@5 (S55) | T67.3 passes |
| 8 | Verify hard negatives are confirmed different-topic | T67.4 passes |
| 9 | Staged backfill: one subject at a time | T67.5 passes |
| 10 | Verify rollback to prior version possible | T67.6 passes |
| 11 | Per-subject before/after comparison | T67.7 passes |

**Atomic Sub-tasks:**
1. Hard negative mining pipeline with faiss-gpu
2. Contrastive training pipeline with sentence-transformers
3. Evaluation framework (clustering purity, cross-session accuracy, retrieval precision)
4. Staged backfill with resumable progress
5. Rollback mechanism

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Hard negative mining returns mislabelled positives | Validate against ground truth labels; discard false negatives |
| Training diverges | Reduce learning rate; check gradient norms |
| Clustering purity decreases | Revert to previous model; analyze data distribution |
| Backfill fails mid-subject | Resume from last checkpoint; do not restart |
| Rollback corrupts embeddings | Keep previous version embeddings; swap references |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Pipeline Pattern: Data preparation → Mining → Training → Evaluation → Rollout
- Strategy Pattern: Model swapping via config
- Checkpoint Pattern: Resumable backfill with progress tracking

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case.py
- Model versions: emb-v{major}.{minor}.{patch}

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Training scripts: separate from serving code

**Type Safety:**
- All function signatures must have type hints
- Pydantic models enforce strict validation
- Type hints for ML tensors and data structures

---

### 5. API & Interface Contracts

**FastAPI Endpoints:**
```
POST   /api/v1/embeddings/train         → 202 ContrastiveResult
GET    /api/v1/embeddings/versions       → 200 list[EmbeddingVersion]
POST   /api/v1/embeddings/activate       → 200 EmbeddingVersion
GET    /api/v1/embeddings/active         → 200 EmbeddingVersion
POST   /api/v1/embeddings/backfill       → 202 BackfillStatus
GET    /api/v1/embeddings/backfill/{id}  → 200 BackfillStatus
```

**Request/Response Payloads:**
```json
// POST /api/v1/embeddings/train
// Request:
{
  "base_model": "BAAI/bge-base-en-v1.5",
  "training_data_version": "v1.2.3",
  "hard_negative_samples": 10000,
  "learning_rate": 2e-5,
  "num_epochs": 3
}
// Response 202:
{
  "model_version": "emb-v1.0.0",
  "clustering_purity": 0.89,
  "cross_session_accuracy": 0.85,
  "retrieval_precision_at_5": 0.92,
  "hard_negatives_mined": 10000,
  "training_samples": 50000,
  "created_at": "2026-09-12T10:30:00Z"
}

// POST /api/v1/embeddings/backfill
// Request:
{
  "model_version": "emb-v1.0.0",
  "subject_id": "550e8400-e29b-41d4-a716-446655440000",
  "batch_size": 1000
}
// Response 202:
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "model_version": "emb-v1.0.0",
  "subject_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "processed_count": 0,
  "total_count": 15000,
  "created_at": "2026-09-12T10:30:00Z"
}
```

**Config Contract (`config/models.yaml`):**
```yaml
embedding_model:
  active_version: "emb-v1.0.0"
  fallback_version: "emb-v0.9.0"
  enable_fallback: true
  backfill_batch_size: 1000
  backfill_resumable: true
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection | `postgresql+asyncpg://localhost:5432/lis` |
| `TRAINING_GPU_ENABLED` | bool | Enable GPU for training | `true` |
| `MODEL_CACHE_DIR` | string | Local model cache | `/data/models` |
| `DVC_REMOTE` | string | DVC remote storage | `s3://lis-training-data` |
| `FAISS_GPU_ENABLED` | bool | Enable faiss-gpu for hard negative mining | `true` |

**Third-Party Integration Contracts:**
- faiss-gpu: Hard negative mining over full corpus
- sentence-transformers: Contrastive training framework
- Model storage: Local filesystem or S3 for model artifacts

**Version Pins:**
- PyTorch: 2.3.x
- sentence-transformers: 3.x
- faiss-gpu: 1.8.x

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T67.1 | V | Fine-tuned embedding model exists | Evaluated on S05 labels | Clustering purity improves over Qwen3 baseline |
| T67.2 | V | Fine-tuned embedding model exists | Evaluated on cross-session topic matching | Accuracy improves over S32 T32.1 baseline |
| T67.3 | V | Fine-tuned embedding model exists | Evaluated on retrieval precision@5 | Precision improves or holds vs S55 baseline |
| T67.4 | I | Hard negative mining pipeline runs | Returns nearest neighbours | All neighbours are confirmed different-topic (no mislabelled positives) |
| T67.5 | I | Backfill configured for one subject | Backfill runs | Backfill is resumable; both versions coexist safely during rollout |
| T67.6 | I | New model version is active | Rollback requested | Rollback to prior version possible without data loss |
| T67.7 | V | New model version is active | Per-subject before/after comparison | No regression on any subject |

**Verification Commands:**
```bash
# Full local verification
uv run alembic upgrade head && \
uv run pytest tests/ -m integration -v -k "S67 or embedding_finetune" && \
uv run pytest tests/ -m ml -v -k "contrastive" && \
uv run mypy --strict src/models/embedding_finetune/ src/serving/embeddings/ && \
uv run ruff check src/models/embedding_finetune/ src/serving/embeddings/
```

**Exit Criteria:**
- [ ] Clustering purity improves over baseline
- [ ] Cross-session topic matching accuracy improves
- [ ] Retrieval precision@5 improves or holds
- [ ] Hard negatives are confirmed different-topic
- [ ] Staged backfill works correctly
- [ ] Rollback to prior version possible
- [ ] No regression on any subject

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Hard negative mining can return mislabelled positives; validate against ground truth
- Training can diverge; monitor gradient norms and loss
- Clustering purity may decrease on some subjects; need per-subject analysis
- Backfill can fail mid-subject; must be resumable
- Rollback must not corrupt embeddings; keep previous version references

**Fallback Instructions:**
- If training diverges, reduce learning rate and restart
- If clustering purity decreases, revert to previous model
- If backfill fails, resume from last checkpoint
- If rollback fails, restore from backup embeddings

**Rollback Procedure:**
- Model: Activate previous version via `POST /api/v1/embeddings/activate`
- Config: Set `enable_fallback: true` in `config/models.yaml`
- Embeddings: Keep previous version embeddings; swap references in `embedding_versions`

---

### 9. Observability

**Metrics Added:**
- `embedding_training_loss`: Gauge of current training loss
- `embedding_clustering_purity`: Gauge of current clustering purity
- `embedding_backfill_progress`: Gauge of backfill progress (0-100%)
- `embedding_backfill_errors_total`: Counter of backfill errors
- `embedding_rollback_total`: Counter of rollback operations

**Tracing/Logging:**
- Span: `embedding.contrastive_train` for training runs
- Span: `embedding.hard_negative_mine` for mining operations
- Span: `embedding.backfill` for backfill operations
- Log event: `embedding_model_activated` with model_version
- Log event: `embedding_backfill_completed` with subject_id, processed_count

**Alerts:**
- Alert if clustering purity drops below baseline
- Alert if backfill fails 3 times consecutively
- Alert if rollback is triggered

---

### 10. Exit Checklist

- [ ] All tests pass (T67.1, T67.2, T67.3, T67.4, T67.5, T67.6, T67.7)
- [ ] Clustering purity improves over baseline
- [ ] Cross-session topic matching accuracy improves
- [ ] Retrieval precision@5 improves or holds
- [ ] Hard negatives are confirmed different-topic
- [ ] Staged backfill works correctly
- [ ] Rollback to prior version possible
- [ ] No regression on any subject
- [ ] Observability metrics and alerts configured
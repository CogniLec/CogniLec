# S66 — A1 Classifier Distillation
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Distil the large model's relevance judgments into a small dedicated classifier that matches accuracy at far higher throughput, potentially CPU-servable, while maintaining zero core-content utterances discarded.

**Component Boundaries:**
- **Allowed:** `src/models/a1_distillation/`, `src/training/distillation/`, `src/serving/a1_classifier/`, `config/models.yaml`, `tests/`
- **Off-limits:** ASR models (S68), embedding models (S67), LoRA adapters (S69), core schema (S07)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12.x | Runtime |
| PyTorch | 2.3.x | ML framework |
| sentence-transformers | 3.x | SetFit classifier |
| Unsloth | latest | PEFT fine-tuning |
| vLLM | 0.5.x | Model serving |
| scikit-learn | 1.5.x | Evaluation metrics |
| DVC | 3.x | Dataset versioning |

---

### 2. State Machine & Domain Schemas

**Model Training Pipeline State:**
```
data_preparation → label_generation → validation → training → evaluation → deployment
```

**Pydantic Schemas:**

```python
# src/api/schemas/a1_distillation.py
class DistillationConfig(BaseModel):
    base_model: str = "Qwen/Qwen3-0.5B"
    training_data_version: str
    validation_split: float = 0.2
    max_samples: int = 5000
    learning_rate: float = 2e-5
    num_epochs: int = 3
    batch_size: int = 32
    warmup_ratio: float = 0.1
    weight_decay: float = 0.01

class DistillationResult(BaseModel):
    model_version: str
    precision: float
    recall: float
    f1_score: float
    throughput_ratio: float  # vs large model
    zero_discard_assertion: bool
    training_samples: int
    validation_samples: int
    created_at: datetime

class ABTestConfig(BaseModel):
    model_version: str
    traffic_percentage: float = 0.1
    duration_hours: int = 24
    metrics: list[str] = ["note_quality", "latency", "cost"]
```

**SQLAlchemy Models:**

```python
# src/db/models/a1_classifier.py
class A1ClassifierVersion(Base):
    __tablename__ = "a1_classifier_versions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    version: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    base_model: Mapped[str] = mapped_column(String(255), nullable=False)
    training_data_version: Mapped[str] = mapped_column(String(50), nullable=False)
    precision: Mapped[float] = mapped_column(Float, nullable=False)
    recall: Mapped[float] = mapped_column(Float, nullable=False)
    f1_score: Mapped[float] = mapped_column(Float, nullable=False)
    throughput_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    zero_discard_assertion: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create Alembic migration for `a1_classifier_versions` table | `alembic upgrade head` succeeds |
| 2 | Generate ~5k labels using primary LLM on unlabeled utterances | Label file exists with 5k samples |
| 3 | Combine with S05 2k human-labelled set and S65 corrections | Combined dataset has no duplicates |
| 4 | Validate combined dataset against S42 held-out set | Validation metrics computed |
| 5 | Fine-tune SetFit classifier using Unsloth/PEFT | Training completes; model saved |
| 6 | Evaluate precision/recall against large model on S42 set | T66.1, T66.2 pass |
| 7 | Measure throughput vs large model | T66.3 passes (20x improvement) |
| 8 | Verify zero core-content utterances discarded | T66.4 passes |
| 9 | Integrate classifier with config-based swapping | T66.5 passes |
| 10 | Run A/B test on live sessions | T66.6 passes |

**Atomic Sub-tasks:**
1. Dataset preparation (LLM labelling + human labels + corrections)
2. Model training pipeline (SetFit/Unsloth)
3. Evaluation framework (precision, recall, throughput, zero-discard)
4. Serving integration with config-based model swapping
5. A/B testing framework

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| LLM labelling produces inconsistent labels | Use confidence threshold; discard low-confidence labels |
| Training data imbalance (keep vs discard) | Use class weights or oversampling |
| Model overfits to training data | Early stopping; dropout; regularization |
| Throughput target not met | Optimize batch size; consider quantization |
| Zero-discard assertion fails | Fall back to large model immediately |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Pipeline Pattern: Data preparation → Training → Evaluation → Deployment
- Strategy Pattern: Model swapping via config
- Observer Pattern: A/B test metrics collection

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case.py
- Model versions: v{major}.{minor}.{patch} (semantic versioning)

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
POST   /api/v1/a1-classifier/train      → 202 DistillationResult
GET    /api/v1/a1-classifier/versions    → 200 list[A1ClassifierVersion]
POST   /api/v1/a1-classifier/activate    → 200 A1ClassifierVersion
GET    /api/v1/a1-classifier/active      → 200 A1ClassifierVersion
POST   /api/v1/a1-classifier/evaluate    → 200 DistillationResult
```

**Request/Response Payloads:**
```json
// POST /api/v1/a1-classifier/train
// Request:
{
  "base_model": "Qwen/Qwen3-0.5B",
  "training_data_version": "v1.2.3",
  "max_samples": 5000,
  "learning_rate": 2e-5,
  "num_epochs": 3
}
// Response 202:
{
  "model_version": "a1-classifier-v1.0.0",
  "precision": 0.94,
  "recall": 0.92,
  "f1_score": 0.93,
  "throughput_ratio": 25.3,
  "zero_discard_assertion": true,
  "training_samples": 5000,
  "validation_samples": 1000,
  "created_at": "2026-09-12T10:30:00Z"
}

// POST /api/v1/a1-classifier/activate
// Request:
{
  "model_version": "a1-classifier-v1.0.0"
}
// Response 200: (activated version with is_active=true)
```

**Model Serving Contract:**
```python
# src/serving/a1_classifier/classifier.py
class A1Classifier:
    async def predict(self, utterance: str, context: dict) -> A1Prediction:
        """Predict relevance of utterance for note inclusion."""
        pass

    async def predict_batch(self, utterances: list[str], contexts: list[dict]) -> list[A1Prediction]:
        """Batch prediction for efficiency."""
        pass

class A1Prediction(BaseModel):
    relevant: bool
    confidence: float
    model_version: str
    latency_ms: float
```

**Config Contract (`config/models.yaml`):**
```yaml
a1_classifier:
  active_version: "a1-classifier-v1.0.0"
  fallback_model: "Qwen/Qwen3-0.5B"
  enable_fallback: true
  max_batch_size: 64
  confidence_threshold: 0.7
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection | `postgresql+asyncpg://localhost:5432/lis` |
| `LLM_API_KEY` | string | API key for labelling LLM | `sk-...` |
| `LLM_API_BASE` | string | LLM API endpoint | `https://api.openai.com/v1` |
| `TRAINING_GPU_ENABLED` | bool | Enable GPU for training | `true` |
| `MODEL_CACHE_DIR` | string | Local model cache | `/data/models` |
| `DVC_REMOTE` | string | DVC remote storage | `s3://lis-training-data` |

**Third-Party Integration Contracts:**
- LLM API: OpenAI-compatible API for label generation
- GPU: CUDA-enabled GPU for training (optional for inference)
- Model storage: Local filesystem or S3 for model artifacts

**Version Pins:**
- PyTorch: 2.3.x
- sentence-transformers: 3.x
- Unsloth: latest stable
- vLLM: 0.5.x

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T66.1 | V | Distilled classifier is trained on combined dataset | Evaluated on S42 held-out set | Precision within 2 points of large model (≥ large_model_precision - 0.02) |
| T66.2 | V | Distilled classifier is trained on combined dataset | Evaluated on S42 held-out set | Recall within 3 points of large model (≥ large_model_recall - 0.03) |
| T66.3 | P | Distilled classifier is deployed | 1000 utterances processed | Throughput ≥ 20x large model per utterance |
| T66.4 | V | Distilled classifier is active | Process core-content utterances | Zero core-content utterances discarded (S42 T42.4 assertion holds) |
| T66.5 | I | Classifier version exists in registry | Config updated to new version | Classifier swapped; large model remains fallback |
| T66.6 | V | A/B test configured with 10% traffic | Live sessions processed for 24h | No quality regression in resulting notes (p > 0.05) |

**Verification Commands:**
```bash
# Full local verification
uv run alembic upgrade head && \
uv run pytest tests/ -m integration -v -k "S66 or a1_distillation" && \
uv run pytest tests/ -m ml -v -k "a1_classifier" && \
uv run mypy --strict src/models/a1_distillation/ src/serving/a1_classifier/ && \
uv run ruff check src/models/a1_distillation/ src/serving/a1_classifier/
```

**Exit Criteria:**
- [ ] Precision within 2 points of large model
- [ ] Recall within 3 points of large model
- [ ] Throughput ≥ 20x large model
- [ ] Zero core-content utterances discarded
- [ ] Config-based model swapping works
- [ ] A/B test shows no quality regression

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- LLM labelling can produce inconsistent labels; use confidence thresholding
- Training data imbalance can bias model; use class weights
- Overfitting to training data; use early stopping and regularization
- Throughput target may require quantization or batch optimization
- Zero-discard assertion is critical; never deploy if it fails

**Fallback Instructions:**
- If precision/recall targets not met, increase training data or adjust hyperparameters
- If throughput target not met, try quantization (INT8/INT4) or smaller model
- If zero-discard fails, immediately revert to large model fallback
- If A/B test shows regression, stop test and revert to previous version

**Rollback Procedure:**
- Model: Activate previous version via `POST /api/v1/a1-classifier/activate`
- Config: Set `enable_fallback: true` in `config/models.yaml`
- Database: Update `is_active` flag on classifier versions

---

### 9. Observability

**Metrics Added:**
- `a1_classifier_predictions_total`: Counter by prediction (relevant/not relevant)
- `a1_classifier_latency_ms`: Histogram of prediction latency
- `a1_classifier_confidence_histogram`: Histogram of confidence scores
- `a1_classifier_fallback_total`: Counter of fallback to large model
- `a1_classifier_throughput_ratio`: Gauge of current throughput vs large model

**Tracing/Logging:**
- Span: `a1_classifier.predict` for each prediction
- Span: `a1_classifier.train` for training runs
- Log event: `a1_classifier_activated` with model_version
- Log event: `a1_classifier_fallback_triggered` with reason

**Alerts:**
- Alert if precision drops below threshold (large_model_precision - 0.03)
- Alert if recall drops below threshold (large_model_recall - 0.04)
- Alert if fallback rate > 10%
- Alert if throughput ratio < 15x

---

### 10. Exit Checklist

- [ ] All tests pass (T66.1, T66.2, T66.3, T66.4, T66.5, T66.6)
- [ ] Distilled classifier precision/recall within targets
- [ ] Throughput ≥ 20x large model
- [ ] Zero core-content utterances discarded
- [ ] Config-based model swapping works
- [ ] A/B test shows no quality regression
- [ ] Fallback to large model works correctly
- [ ] Observability metrics and alerts configured
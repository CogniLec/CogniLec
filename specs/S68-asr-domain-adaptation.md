# S68 — ASR Domain Adaptation
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Fine-tune the selected ASR model on 10-20h of transcribed local audio to improve recognition accuracy for the actual deployment environment, with measured, broad improvement across all conditions.

**Component Boundaries:**
- **Allowed:** `src/models/asr_finetune/`, `src/training/asr/`, `src/serving/asr/`, `config/models.yaml`, `tests/`
- **Off-limits:** A1 classifier (S66), embedding models (S67), LoRA adapters (S69), core schema (S07)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12.x | Runtime |
| PyTorch | 2.3.x | ML framework |
| Transformers | 4.40.x | Hugging Face models |
| Whisper/Jamba | latest | ASR model |
| jiwer | 3.x | WER computation |
| DVC | 3.x | Dataset versioning |
| torchaudio | 2.3.x | Audio processing |

---

### 2. State Machine & Domain Schemas

**Training Pipeline State:**
```
data_preparation → preprocessing → training → evaluation → conditional_validation → deployment
```

**Pydantic Schemas:**

```python
# src/api/schemas/asr_finetune.py
class ASRFineTuneConfig(BaseModel):
    base_model: str = "openai/whisper-large-v3"
    training_data_version: str
    audio_hours: float = 15.0
    learning_rate: float = 1e-5
    num_epochs: int = 5
    batch_size: int = 8
    gradient_accumulation_steps: int = 4
    warmup_ratio: float = 0.1
    weight_decay: float = 0.01
    max_grad_norm: float = 1.0

class ASRFineTuneResult(BaseModel):
    model_version: str
    wer_improvement: float
    per_condition_wer: dict[str, float]
    general_domain_wer: float
    technical_vocab_wer: float
    hallucination_rate: float
    training_hours: float
    created_at: datetime

class ConditionEvaluation(BaseModel):
    condition: str  # room, lecturer, subject, accent
    wer_before: float
    wer_after: float
    improvement: float
    sample_count: int
```

**SQLAlchemy Models:**

```python
# src/db/models/asr_version.py
class ASRVersion(Base):
    __tablename__ = "asr_versions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    version: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    base_model: Mapped[str] = mapped_column(String(255), nullable=False)
    training_data_version: Mapped[str] = mapped_column(String(50), nullable=False)
    wer_improvement: Mapped[float] = mapped_column(Float, nullable=False)
    per_condition_wer: Mapped[dict] = mapped_column(JSONB, nullable=False)
    general_domain_wer: Mapped[float] = mapped_column(Float, nullable=False)
    technical_vocab_wer: Mapped[float] = mapped_column(Float, nullable=False)
    hallucination_rate: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create Alembic migration for `asr_versions` table | `alembic upgrade head` succeeds |
| 2 | Collect 10-20h transcribed local audio across conditions | Audio dataset assembled |
| 3 | Preprocess audio: normalize, chunk, align transcripts | Preprocessed dataset ready |
| 4 | Fine-tune ASR model on local audio | Training completes; model saved |
| 5 | Evaluate WER on held-out local audio | T68.1 passes |
| 6 | Evaluate per-condition WER (S04 conditions) | T68.2 passes |
| 7 | Evaluate on general-domain audio | T68.3 passes (no regression) |
| 8 | Evaluate technical vocabulary recognition | T68.4 passes |
| 9 | Evaluate hallucination rate (S22 metric) | T68.5 passes |
| 10 | Integrate model with config-based swapping | T68.6 passes |

**Atomic Sub-tasks:**
1. Audio data collection and preprocessing
2. ASR fine-tuning pipeline
3. Multi-condition evaluation framework
4. Serving integration with config-based model swapping
5. Hallucination rate monitoring

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Insufficient audio for some conditions | Augment with synthetic data; note limitations |
| Overfitting to specific room/lecturer | Use dropout; early stopping; regularization |
| Hallucination rate increases | Reduce fine-tuning epochs; adjust loss function |
| General domain WER regresses | Stop training; revert to previous model |
| Model too large for inference hardware | Quantize model (INT8/INT4); use smaller base |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Pipeline Pattern: Data preparation → Training → Evaluation → Deployment
- Strategy Pattern: Model swapping via config
- Observer Pattern: Per-condition evaluation monitoring

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case.py
- Model versions: asr-v{major}.{minor}.{patch}

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
POST   /api/v1/asr/train          → 202 ASRFineTuneResult
GET    /api/v1/asr/versions        → 200 list[ASRVersion]
POST   /api/v1/asr/activate        → 200 ASRVersion
GET    /api/v1/asr/active          → 200 ASRVersion
POST   /api/v1/asr/evaluate        → 200 ASRFineTuneResult
GET    /api/v1/asr/conditions      → 200 list[ConditionEvaluation]
```

**Request/Response Payloads:**
```json
// POST /api/v1/asr/train
// Request:
{
  "base_model": "openai/whisper-large-v3",
  "training_data_version": "v1.2.3",
  "audio_hours": 15.0,
  "learning_rate": 1e-5,
  "num_epochs": 5
}
// Response 202:
{
  "model_version": "asr-v1.0.0",
  "wer_improvement": 0.12,
  "per_condition_wer": {
    "room_a": 0.08,
    "room_b": 0.10,
    "lecturer_1": 0.09,
    "lecturer_2": 0.11,
    "subject_math": 0.07,
    "subject_cs": 0.09
  },
  "general_domain_wer": 0.05,
  "technical_vocab_wer": 0.06,
  "hallucination_rate": 0.02,
  "training_hours": 15.0,
  "created_at": "2026-09-12T10:30:00Z"
}

// POST /api/v1/asr/evaluate
// Request:
{
  "model_version": "asr-v1.0.0",
  "evaluation_dataset": "held-out-local-v1.2.3"
}
// Response 200: (same as above)
```

**Config Contract (`config/models.yaml`):**
```yaml
asr_model:
  active_version: "asr-v1.0.0"
  fallback_version: "asr-v0.9.0"
  enable_fallback: true
  max_batch_size: 32
  beam_size: 5
  language: "en"
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
| `AUDIO_DATA_DIR` | string | Local audio data directory | `/data/audio` |

**Third-Party Integration Contracts:**
- Hugging Face Transformers: Model loading and fine-tuning
- torchaudio: Audio processing and loading
- jiwer: WER computation
- Model storage: Local filesystem or S3 for model artifacts

**Version Pins:**
- PyTorch: 2.3.x
- Transformers: 4.40.x
- torchaudio: 2.3.x
- jiwer: 3.x

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T68.1 | V | Fine-tuned ASR model exists | Evaluated on held-out local audio | WER improves over S06 baseline |
| T68.2 | V | Fine-tuned ASR model exists | Evaluated across all S04 conditions | Improvement holds across all conditions (not just best-represented) |
| T68.3 | V | Fine-tuned ASR model exists | Evaluated on general-domain audio | No regression on general-domain audio (guards against catastrophic forgetting) |
| T68.4 | V | Fine-tuned ASR model exists | Evaluated on technical-vocabulary test set | Technical vocabulary recognition improved |
| T68.5 | V | Fine-tuned ASR model exists | Hallucination rate measured (S22 metric) | Hallucination rate not increased by fine-tuning |
| T68.6 | I | ASR version exists in registry | Config updated to new version | Model swapped in by config; base model retained as fallback |

**Verification Commands:**
```bash
# Full local verification
uv run alembic upgrade head && \
uv run pytest tests/ -m integration -v -k "S68 or asr_finetune" && \
uv run pytest tests/ -m ml -v -k "asr" && \
uv run mypy --strict src/models/asr_finetune/ src/serving/asr/ && \
uv run ruff check src/models/asr_finetune/ src/serving/asr/
```

**Exit Criteria:**
- [ ] WER improves over S06 baseline on held-out local audio
- [ ] Improvement holds across all S04 conditions
- [ ] No regression on general-domain audio
- [ ] Technical vocabulary recognition improved
- [ ] Hallucination rate not increased
- [ ] Config-based model swapping works

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Insufficient audio for some conditions; need augmentation or synthetic data
- Overfitting to specific rooms/lecturers; use regularization
- Hallucination rate may increase; monitor closely
- General domain WER may regress; stop training early
- Model size may exceed hardware limits; quantize or use smaller base

**Fallback Instructions:**
- If WER improvement insufficient, collect more training data
- If overfitting occurs, increase dropout and early stopping patience
- If hallucination rate increases, reduce training epochs
- If general domain regresses, revert to previous model immediately
- If model too large, quantize to INT8/INT4 or use smaller base model

**Rollback Procedure:**
- Model: Activate previous version via `POST /api/v1/asr/activate`
- Config: Set `enable_fallback: true` in `config/models.yaml`
- Database: Update `is_active` flag on ASR versions

---

### 9. Observability

**Metrics Added:**
- `asr_wer_current`: Gauge of current WER on held-out set
- `asr_wer_per_condition`: Gauge per condition (room, lecturer, subject)
- `asr_hallucination_rate`: Gauge of hallucination rate
- `asr_training_loss`: Gauge of training loss
- `asr_fallback_total`: Counter of fallback to base model

**Tracing/Logging:**
- Span: `asr.finetune` for training runs
- Span: `asr.evaluate` for evaluation runs
- Log event: `asr_model_activated` with model_version, wer_improvement
- Log event: `asr_evaluation_completed` with per_condition_wer

**Alerts:**
- Alert if WER improvement < 5%
- Alert if hallucination rate > 5%
- Alert if general domain WER regresses > 2%
- Alert if fallback rate > 10%

---

### 10. Exit Checklist

- [ ] All tests pass (T68.1, T68.2, T68.3, T68.4, T68.5, T68.6)
- [ ] WER improves over S06 baseline
- [ ] Improvement holds across all conditions
- [ ] No regression on general-domain audio
- [ ] Technical vocabulary recognition improved
- [ ] Hallucination rate not increased
- [ ] Config-based model swapping works
- [ ] Observability metrics and alerts configured
# S69 — Multi-LoRA Serving & Adapter Registry
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Serve multiple agent-specific LoRA adapters from a single base model in VRAM, with adapter registry, version pinning, and fallback to base model on adapter failure.

**Component Boundaries:**
- **Allowed:** `src/serving/multi_lora/`, `src/models/lora_adapters/`, `config/models.yaml`, `config/adapters/`, `tests/`
- **Off-limits:** A1 classifier (S66), embedding models (S67), ASR models (S68), core schema (S07)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12.x | Runtime |
| vLLM | 0.5.x | Multi-LoRA serving |
| PyTorch | 2.3.x | ML framework |
| PEFT | 0.11.x | LoRA adapter management |
| Hugging Face Transformers | 4.40.x | Model loading |
| Pydantic | 2.13.5 | Validation |

---

### 2. State Machine & Domain Schemas

**Adapter Lifecycle:**
```
registered → loaded → active → (failed → fallback) → deactivated
```

**Pydantic Schemas:**

```python
# src/api/schemas/lora_adapters.py
class AdapterConfig(BaseModel):
    adapter_id: str = Field(..., pattern=r"^[a-z0-9-]+$")
    agent_id: str = Field(..., pattern=r"^[A-Z0-9]+$")  # A2, A5, A6
    base_model: str
    adapter_path: str
    rank: int = 16
    alpha: float = 32.0
    target_modules: list[str] = ["q_proj", "v_proj"]
    version: str
    description: str | None = None

class AdapterResponse(BaseModel):
    adapter_id: str
    agent_id: str
    base_model: str
    version: str
    status: str  # loaded, active, failed, deactivated
    created_at: datetime
    activated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)

class AdapterSwapRequest(BaseModel):
    agent_id: str
    adapter_id: str

class AdapterSwapResponse(BaseModel):
    agent_id: str
    previous_adapter: str | None
    new_adapter: str
    swap_latency_ms: float

class AgentRoutingConfig(BaseModel):
    agent_id: str
    adapter_id: str | None  # None = use base model
    fallback_to_base: bool = True
```

**SQLAlchemy Models:**

```python
# src/db/models/lora_adapter.py
class LoRAAdapter(Base):
    __tablename__ = "lora_adapters"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    adapter_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    agent_id: Mapped[str] = mapped_column(String(50), nullable=False)
    base_model: Mapped[str] = mapped_column(String(255), nullable=False)
    adapter_path: Mapped[str] = mapped_column(String(500), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=16)
    alpha: Mapped[float] = mapped_column(Float, nullable=False, default=32.0)
    target_modules: Mapped[list] = mapped_column(JSONB, nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="registered")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('registered', 'loaded', 'active', 'failed', 'deactivated')",
            name="ck_adapter_status"
        ),
        UniqueConstraint("agent_id", "is_active", name="uq_agent_active_adapter"),
    )
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create Alembic migration for `lora_adapters` table | `alembic upgrade head` succeeds |
| 2 | Create adapter registry in `config/models.yaml` | Registry file exists with all adapters |
| 3 | Implement vLLM multi-LoRA serving configuration | vLLM starts with multiple adapters |
| 4 | Create A2 style LoRA from S65 note edits | A2 adapter trained and registered |
| 5 | Create A6 extraction LoRA | A6 adapter trained and registered |
| 6 | Implement agent-to-adapter routing | T69.2 passes |
| 7 | Measure adapter swap latency | T69.3 passes |
| 8 | Evaluate A2 style LoRA quality | T69.4 passes |
| 9 | Evaluate A6 extraction accuracy | T69.5 passes |
| 10 | Record adapter version on agent_runs | T69.6 passes |
| 11 | Implement fallback on adapter failure | T69.7 passes |

**Atomic Sub-tasks:**
1. Adapter registry and config management
2. vLLM multi-LoRA serving setup
3. A2 style LoRA training pipeline
4. A6 extraction LoRA training pipeline
5. Agent-to-adapter routing logic
6. Fallback mechanism on adapter failure

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Adapter fails to load | Fall back to base model; log error |
| Adapter swap takes too long | Timeout after 100ms; use base model |
| Agent requests non-existent adapter | Fall back to base model; log warning |
| Multiple adapters for same agent | Use most recently activated; deactivate others |
| Base model reload required | Reload with all adapters; brief downtime |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Registry Pattern: Adapter registry with version pinning
- Strategy Pattern: Agent-to-adapter routing
- Circuit Breaker Pattern: Fallback on adapter failure

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case.py
- Adapter IDs: agent-lowercase-version (e.g., `a2-style-v1.0.0`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Adapter training scripts: separate from serving code

**Type Safety:**
- All function signatures must have type hints
- Pydantic models enforce strict validation
- Type hints for ML tensors and data structures

---

### 5. API & Interface Contracts

**FastAPI Endpoints:**
```
POST   /api/v1/adapters              → 201 AdapterResponse
GET    /api/v1/adapters              → 200 list[AdapterResponse]
GET    /api/v1/adapters/{adapter_id} → 200 AdapterResponse
POST   /api/v1/adapters/swap         → 200 AdapterSwapResponse
GET    /api/v1/adapters/active       → 200 list[AdapterResponse]
POST   /api/v1/adapters/{adapter_id}/activate → 200 AdapterResponse
POST   /api/v1/adapters/{adapter_id}/deactivate → 200 AdapterResponse
```

**Request/Response Payloads:**
```json
// POST /api/v1/adapters
// Request:
{
  "adapter_id": "a2-style-v1.0.0",
  "agent_id": "A2",
  "base_model": "Qwen/Qwen3-0.5B",
  "adapter_path": "/data/adapters/a2-style-v1.0.0",
  "rank": 16,
  "alpha": 32.0,
  "target_modules": ["q_proj", "v_proj"],
  "version": "1.0.0",
  "description": "Note style LoRA for A2 agent"
}
// Response 201:
{
  "adapter_id": "a2-style-v1.0.0",
  "agent_id": "A2",
  "base_model": "Qwen/Qwen3-0.5B",
  "version": "1.0.0",
  "status": "registered",
  "created_at": "2026-09-12T10:30:00Z",
  "activated_at": null
}

// POST /api/v1/adapters/swap
// Request:
{
  "agent_id": "A2",
  "adapter_id": "a2-style-v1.0.0"
}
// Response 200:
{
  "agent_id": "A2",
  "previous_adapter": "a2-style-v0.9.0",
  "new_adapter": "a2-style-v1.0.0",
  "swap_latency_ms": 45.2
}
```

**Adapter Registry (`config/models.yaml`):**
```yaml
multi_lora:
  base_model: "Qwen/Qwen3-0.5B"
  max_adapters: 8
  adapter_swap_timeout_ms: 100
  fallback_to_base: true

adapters:
  - adapter_id: "a2-style-v1.0.0"
    agent_id: "A2"
    version: "1.0.0"
    path: "/data/adapters/a2-style-v1.0.0"
    rank: 16
    alpha: 32.0
    target_modules: ["q_proj", "v_proj"]

  - adapter_id: "a6-extraction-v1.0.0"
    agent_id: "A6"
    version: "1.0.0"
    path: "/data/adapters/a6-extraction-v1.0.0"
    rank: 16
    alpha: 32.0
    target_modules: ["q_proj", "v_proj"]

agent_routing:
  A2: "a2-style-v1.0.0"
  A5: null  # use base model
  A6: "a6-extraction-v1.0.0"
```

**vLLM Serving Configuration:**
```yaml
# vllm_multi_lora.yaml
model: "Qwen/Qwen3-0.5B"
enable_lora: true
max_lora_rank: 64
max_loras: 8
lora_modules:
  - "a2-style=/data/adapters/a2-style-v1.0.0"
  - "a6-extraction=/data/adapters/a6-extraction-v1.0.0"
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection | `postgresql+asyncpg://localhost:5432/lis` |
| `VLLM_HOST` | string | vLLM server host | `localhost` |
| `VLLM_PORT` | int | vLLM server port | `8000` |
| `ADAPTER_DIR` | string | Local adapter directory | `/data/adapters` |
| `MAX_ADAPTERS` | int | Maximum concurrent adapters | `8` |
| `ADAPTER_SWAP_TIMEOUT_MS` | int | Timeout for adapter swap | `100` |

**Third-Party Integration Contracts:**
- vLLM: Multi-LoRA serving with adapter hot-swapping
- PEFT: LoRA adapter management and loading
- Hugging Face Transformers: Base model loading

**Version Pins:**
- vLLM: 0.5.x
- PEFT: 0.11.x
- Transformers: 4.40.x

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T69.1 | I | Multiple adapters registered | vLLM starts | Multiple adapters served concurrently from one base model |
| T69.2 | I | Agent routing config exists | Agent sends request | Agent receives correct adapter; each agent gets its own adapter |
| T69.3 | P | Adapter swap requested | Measure latency | Adapter swap adds negligible latency (<100ms) vs base-model inference |
| T69.4 | V | A2 style LoRA is active | Generate notes | A2 style LoRA produces notes rated closer to human-preferred examples than base (S44 T44.4 rubric) |
| T69.5 | V | A6 extraction LoRA is active | Extract syllabus | A6 extraction LoRA improves syllabus extraction accuracy over S50 baseline |
| T69.6 | I | Agent run completes | Check agent_runs row | Adapter version recorded on every agent_runs row |
| T69.7 | I | Adapter fails to load | Agent sends request | Failed adapter load falls back to base model rather than failing the request |

**Verification Commands:**
```bash
# Full local verification
uv run alembic upgrade head && \
uv run pytest tests/ -m integration -v -k "S69 or multi_lora" && \
uv run pytest tests/ -m ml -v -k "lora" && \
uv run mypy --strict src/serving/multi_lora/ src/models/lora_adapters/ && \
uv run ruff check src/serving/multi_lora/ src/models/lora_adapters/
```

**Exit Criteria:**
- [ ] Multiple adapters served concurrently from one base model
- [ ] Agent-to-adapter routing correct
- [ ] Adapter swap latency < 100ms
- [ ] A2 style LoRA improves note quality
- [ ] A6 extraction LoRA improves syllabus extraction
- [ ] Adapter version recorded on agent_runs
- [ ] Fallback to base model on adapter failure

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Adapter load failure should not fail the request; always fallback to base
- Adapter swap timeout may be too aggressive; tune based on hardware
- Multiple adapters for same agent can cause conflicts; enforce one active per agent
- Base model reload required for new adapters; brief downtime
- VRAM limits may restrict concurrent adapters; monitor usage

**Fallback Instructions:**
- If adapter fails to load, fall back to base model immediately
- If adapter swap times out, use base model and log warning
- If VRAM exceeded, reduce max_adapters or use smaller base model
- If base model reload fails, restart vLLM server

**Rollback Procedure:**
- Adapter: Deactivate adapter via `POST /api/v1/adapters/{id}/deactivate`
- Config: Update `agent_routing` in `config/models.yaml` to null
- vLLM: Restart server with previous adapter configuration

---

### 9. Observability

**Metrics Added:**
- `lora_adapter_load_total`: Counter by adapter_id, status (success/failed)
- `lora_adapter_swap_latency_ms`: Histogram of swap latency
- `lora_adapter_active_count`: Gauge of active adapters
- `lora_adapter_fallback_total`: Counter of fallback to base model
- `lora_agent_requests_total`: Counter by agent_id, adapter_id

**Tracing/Logging:**
- Span: `lora.adapter_load` for adapter loading
- Span: `lora.adapter_swap` for adapter swapping
- Log event: `lora_adapter_activated` with adapter_id, agent_id
- Log event: `lora_adapter_failed` with adapter_id, error_message
- Log event: `lora_fallback_triggered` with agent_id, reason

**Alerts:**
- Alert if adapter load failure rate > 5%
- Alert if adapter swap latency > 200ms (p95)
- Alert if fallback rate > 10%
- Alert if VRAM usage > 90%

---

### 10. Exit Checklist

- [ ] All tests pass (T69.1, T69.2, T69.3, T69.4, T69.5, T69.6, T69.7)
- [ ] Multiple adapters served concurrently from one base model
- [ ] Agent-to-adapter routing correct
- [ ] Adapter swap latency < 100ms
- [ ] A2 style LoRA improves note quality
- [ ] A6 extraction LoRA improves syllabus extraction
- [ ] Adapter version recorded on agent_runs
- [ ] Fallback to base model on adapter failure works
- [ ] Observability metrics and alerts configured
# S36 — Local LLM Serving
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Deploy a local GPU-served LLM (Tier 1) via vLLM with an OpenAI-compatible endpoint, co-resident with ASR/TEI on a 4GB VRAM budget.

**Component Boundaries:**
- **Allowed:** `config/models.yaml`, `config/vllm.yaml`, Docker Compose for vLLM service, `src/services/llm/`, `tests/test_vllm_serving.py`
- **Off-limits:** LiteLLM router (S37), prompt versioning (S40), agent implementations (S56–S57)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| vLLM | 0.5.x | OpenAI-compatible LLM serving |
| Phi-3-mini-3.8B-4bit / Qwen2.5-3B-4bit | AWQ quantized | Tier 1 local model |
| CUDA | 12.x | GPU runtime |
| Docker Compose | 2.x | Service orchestration |

---

### 2. State Machine & Domain Schemas

**Model Loading State:**
```
IDLE → DOWNLOADING → LOADED → SERVING → STOPPED
              ↓                     ↑
           FAILED ─────────────────┘
```

**Pydantic Models:**
```python
# src/services/llm/config.py
from pydantic import BaseModel, Field
from enum import Enum

class ModelTier(str, Enum):
    TIER_1 = "tier_1"

class VLLMConfig(BaseModel):
    model_name: str = "microsoft/Phi-3-mini-3.8B-4bit"
    model_path: str | None = None  # local path override
    quantization: str = "awq"
    gpu_memory_utilization: float = Field(default=0.85, ge=0.1, le=1.0)
    max_model_len: int = 4096
    tensor_parallel_size: int = 1
    host: str = "0.0.0.0"
    port: int = 8000
    health_check_interval: int = 30
    max_concurrent: int = 4

class ModelInfo(BaseModel):
    name: str
    tier: ModelTier
    vram_required_gb: float
    quantization: str
    endpoint: str
    status: str  # idle, loading, ready, failed
```

**config/models.yaml:**
```yaml
tiers:
  tier_1:
    model: microsoft/Phi-3-mini-3.8B-4bit
    quantization: awq
    vram_gb: 2.5
    endpoint: http://vllm:8000/v1
    timeout_s: 60
    gpu_required: true
```

**State Transition Rules:**
- IDLE → DOWNLOADING: on service start if model weights not cached
- DOWNLOADING → LOADED: model weights fully downloaded/loaded
- LOADED → SERVING: vLLM starts accepting requests
- SERVING → STOPPED: graceful shutdown
- Any → FAILED: OOM, CUDA error, or health check failure

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Add vLLM service to Docker Compose with GPU reservation and `--gpu-memory-utilization=0.85` | Container starts, `nvidia-smi` shows allocated VRAM |
| 2 | Create `config/models.yaml` with Tier 1 entry and vLLM config | YAML loads without error |
| 3 | Implement `VLLMConfig` and startup script with fixed start order | Config validates, service starts after ASR/TEI |
| 4 | Implement health check endpoint (`/health`) | `curl http://localhost:8000/health` returns 200 |
| 5 | Verify OpenAI-compatible `/v1/chat/completions` endpoint | Completion request returns valid response |
| 6 | Run fragmentation regression test: all services co-start | All containers healthy, VRAM < 4GB total |
| 7 | Run throughput benchmark for NFR-P3 concurrency | P95 latency within SLA |

**Atomic Sub-tasks:**
1. Docker Compose service definition with GPU allocation
2. vLLM startup script enforcing start order (vLLM after ASR/TEI)
3. Health check and OpenAI-compatible endpoint verification
4. VRAM monitoring and fragmentation regression test
5. Restart recovery and throughput benchmark

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| OOM on model load | Reduce `gpu_memory_utilization`, log error, alert |
| Model download fails | Retry 3x with exponential backoff, then mark FAILED |
| CUDA version mismatch | Fail fast at startup with clear error message |
| Health check timeout | Restart container, max 3 restarts before alert |
| VRAM fragmentation (co-resident) | Enforce start order; if fragmentation detected, restart all services in order |
| Model loads FP16 instead of AWQ | Assert model quantization at startup, fail if mismatch |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Config pattern: Pydantic model for all vLLM settings
- Health check pattern: dedicated `/health` endpoint
- Startup ordering pattern: Docker Compose `depends_on` with health checks

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`vllm_config.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files

---

### 5. API & Interface Contracts

**OpenAI-Compatible Endpoint:**
```yaml
POST /v1/chat/completions
Content-Type: application/json

Request:
  model: "phi-3-mini-3.8b-4bit"
  messages:
    - role: "user"
      content: "Explain gradient descent"
  max_tokens: 512
  temperature: 0.7

Response:
  id: "cmpl-xxx"
  object: "chat.completion"
  choices:
    - message:
        role: "assistant"
        content: "Gradient descent is an optimization algorithm..."
      finish_reason: "stop"
  usage:
    prompt_tokens: 12
    completion_tokens: 150
    total_tokens: 162
```

**Health Check:**
```yaml
GET /health
Response: 200 OK
{
  "status": "healthy",
  "model": "phi-3-mini-3.8b-4bit",
  "gpu_memory_used_gb": 2.1,
  "gpu_memory_total_gb": 4.0
}
```

**Docker Compose Addition:**
```yaml
services:
  vllm:
    image: vllm/vllm-openai:latest
    command: >
      --model microsoft/Phi-3-mini-3.8B-4bit
      --quantization awq
      --gpu-memory-utilization 0.85
      --max-model-len 4096
      --host 0.0.0.0
      --port 8000
    ports:
      - "8000:8000"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
    depends_on:
      asr:
        condition: service_healthy
      tei:
        condition: service_healthy
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `VLLM_MODEL` | string | Model ID or path | `microsoft/Phi-3-mini-3.8B-4bit` |
| `VLLM_QUANTIZATION` | string | Quantization method | `awq` |
| `VLLM_GPU_MEMORY_UTIL` | float | GPU memory utilization fraction | `0.85` |
| `VLLM_MAX_MODEL_LEN` | int | Maximum sequence length | `4096` |
| `VLLM_PORT` | int | Serving port | `8000` |
| `VLLM_MAX_CONCURRENT` | int | Max concurrent requests | `4` |
| `NVIDIA_VISIBLE_DEVICES` | string | GPU device assignment | `all` |

**Third-Party Integration Contracts:**
- vLLM OpenAI-compatible API: standard `/v1/chat/completions` interface
- GPU runtime: NVIDIA Container Toolkit required

**Version Pins:**
- vLLM image pinned in Docker Compose
- CUDA version matched to host driver

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T36.1 | I | `pytest tests/test_vllm_serving.py::test_completion_endpoint -v` | Completion endpoint returns 200 with valid response |
| T36.2 | I | `pytest tests/test_vllm_serving.py::test_all_services_coresident -v` | All services (ASR, TEI, LLM) start successfully in declared order |
| T36.3 | P | `pytest tests/test_vllm_serving.py::test_throughput_nfr_p3 -v` | Throughput meets NFR-P3 concurrency requirements |
| T36.4 | I | `pytest tests/test_vllm_serving.py::test_restart_recovery -v` | Service restarts and recovers without manual intervention |
| T36.5 | P | `pytest tests/test_vllm_serving.py::test_vram_headroom -v` | VRAM headroom remains after all services loaded, < 4GB total |
| T36.6 | I | `pytest tests/test_vllm_serving.py::test_model_is_awq_4bit -v` | Model loads at 4-bit AWQ, not FP16 |

**Test Case Details (Given/When/Then):**

**T36.1 — Completion endpoint responds correctly**
- **Given:** vLLM service is running and model is loaded
- **When:** a POST request is sent to `/v1/chat/completions` with a valid prompt
- **Then:** response is 200 with a non-empty `choices[0].message.content` and usage stats

**T36.2 — All co-resident services start together**
- **Given:** ASR, TEI, and vLLM are defined in Docker Compose with start order
- **When:** `docker compose up` is run
- **Then:** all three services reach healthy state within 5 minutes, no OOM kills

**T36.3 — Throughput meets NFR-P3**
- **Given:** vLLM service is running with Tier 1 model
- **When:** 10 concurrent completion requests are sent
- **Then:** P95 latency is within SLA, no request times out

**T36.4 — Service restart recovers without manual intervention**
- **Given:** vLLM service is running and serving requests
- **When:** the container is killed (`docker kill vllm`)
- **Then:** the service restarts and begins serving within 3 minutes

**T36.5 — VRAM headroom remains**
- **Given:** ASR, TEI, and vLLM services are all loaded
- **When:** `nvidia-smi` is queried
- **Then:** total VRAM used is < 4GB, no OOM errors in logs

**T36.6 — Model loads at 4-bit AWQ**
- **Given:** vLLM config specifies AWQ quantization
- **When:** the model loads and serves its first request
- **Then:** model metadata confirms AWQ quantization, not FP16

**Verification Commands:**
```bash
docker compose up -d vllm && \
sleep 120 && \
curl -f http://localhost:8000/health && \
uv run pytest tests/test_vllm_serving.py -v -k "S36 or vllm" && \
uv run mypy --strict src/services/llm/ && \
uv run ruff check src/services/llm/
```

**Exit Criteria:**
- [ ] T36.1 passes — completion endpoint responds correctly
- [ ] T36.2 passes — all co-resident services start together without fragmentation
- [ ] T36.3 passes — throughput meets NFR-P3
- [ ] T36.4 passes — restart recovers automatically
- [ ] T36.5 passes — VRAM headroom maintained, < 4GB total
- [ ] T36.6 passes — model loads as AWQ 4-bit

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- VRAM fragmentation if services start out of order — enforce strict start order via Docker Compose `depends_on`
- vLLM default `gpu_memory_utilization=0.9` causes OOM when co-resident with ASR/TEI — must explicitly set `0.85`
- Model download on first start can be slow — pre-download weights in CI or use a volume mount
- AWQ model must be explicitly requested; vLLM defaults to FP16 if quantization not specified

**Fallback Instructions:**
- If vLLM fails to start: check `nvidia-smi`, verify CUDA driver version, ensure GPU is not held by another process
- If model loads FP16: kill container, verify `--quantization awq` in command, restart
- If health check fails after 5 retries: check vLLM logs for OOM, reduce `gpu_memory_utilization`

**Rollback Procedure:**
- Stop vLLM container: `docker compose stop vllm`
- No database migrations — stateless service
- LLM requests will route to higher tiers via S37 (once implemented)

---

### 9. Observability (if applicable)

**Metrics Added:**
- `vllm_request_total`: counter of completion requests (labels: model, status=success/error)
- `vllm_latency_seconds`: histogram of request latency
- `vllm_tokens_total`: counter of tokens processed (prompt + completion)
- `vllm_gpu_memory_used_bytes`: gauge of VRAM usage
- `vllm_model_load_duration_seconds`: gauge of model load time

**Tracing/Logging:**
- Span: `vllm.completion` with attributes (model, tokens, latency_ms, gpu_memory_used)
- Log: ERROR on OOM, CUDA errors, model load failures
- Log: INFO on model load completion, service startup

**Alerts:**
- VRAM usage > 90% of allocated: risk of OOM
- Model load time > 5 minutes: possible download or hardware issue
- Health check failures > 3 in 5 minutes: service instability

---

### 10. Exit Checklist

- [ ] All tests pass (T36.1, T36.2, T36.3, T36.4, T36.5, T36.6)
- [ ] vLLM serves OpenAI-compatible endpoint on port 8000
- [ ] Start order enforced: ASR → TEI → vLLM
- [ ] VRAM total < 4GB with all services loaded
- [ ] Model confirmed as AWQ 4-bit quantized
- [ ] Service restarts automatically without manual intervention

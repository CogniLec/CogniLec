# S37 — LLM Router & Failover Ladder
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement a five-tier hybrid LLM routing ladder via LiteLLM proxy so that no single model failure can lose a session, with explicit Tier 5 failure handling.

**Component Boundaries:**
- **Allowed:** `config/litellm.yaml`, `src/services/llm/router.py`, `src/services/llm/failover.py`, `tests/test_llm_router.py`
- **Off-limits:** vLLM service itself (S36), schema registry (S38), observability (S39)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| LiteLLM | 1.x | LLM proxy and routing |
| vLLM | 0.5.x | Tier 1 local GPU serving |
| llama.cpp | latest | Tier 2 local CPU serving |
| OpenAI SDK | 1.x | Tier 3 hosted API |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Failover Ladder State:**
```
request → Tier1(local GPU) ──fail──→ Tier2(local CPU) ──fail──→ Tier3(hosted API) ──fail──→ Tier4(cheap hosted) ──fail──→ Tier5(FAIL)
           │                          │                          │                          │
           ↓ success                  ↓ success                  ↓ success                  ↓ success
         response                  response                  response                  response
```

**Pydantic Models:**
```python
# src/services/llm/router.py
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

class LLMTier(str, Enum):
    TIER_1 = "tier_1"  # Local GPU (vLLM)
    TIER_2 = "tier_2"  # Local CPU (llama.cpp)
    TIER_3 = "tier_3"  # Hosted API (OpenAI/Anthropic)
    TIER_4 = "tier_4"  # Hosted cheap (Together/Fireworks/Groq)
    TIER_5 = "tier_5"  # FAIL

class FailoverTrigger(str, Enum):
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SCHEMA_INVALID = "schema_invalid"

class TierConfig(BaseModel):
    tier: LLMTier
    model: str
    endpoint: str
    api_key_env: str | None = None
    timeout_s: int = 60
    max_retries: int = 0  # no retry within tier; failover is the retry

class LLMRouterConfig(BaseModel):
    tiers: list[TierConfig]
    timeout_by_tier: dict[LLMTier, int] = Field(default_factory=lambda: {
        LLMTier.TIER_1: 60,
        LLMTier.TIER_2: 120,
        LLMTier.TIER_3: 30,
        LLMTier.TIER_4: 30,
    })

class RoutingDecision(BaseModel):
    tier: LLMTier
    model: str
    attempt: int
    trigger: FailoverTrigger | None = None
    timestamp: datetime

class LLMResponse(BaseModel):
    content: str
    tier_used: LLMTier
    model: str
    latency_ms: int
    tokens_used: int
    failed: bool = False
    failure_reason: str | None = None
```

**State Transition Rules:**
- Request always starts at Tier 1
- HTTP error → descend one tier
- Timeout → descend one tier (timeout budget per tier)
- Rate limit → descend immediately, no retry-storming
- Schema invalid → one bounded retry at same tier, then descend
- All tiers exhausted → Tier 5: mark session `failed`, never `complete`

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Define `config/litellm.yaml` with all five tiers | Config loads, YAML validates |
| 2 | Implement `LLMRouter` with tier descent logic | Unit test: mock failures trigger descent |
| 3 | Implement timeout budgets per tier | Unit test: timeout triggers descent |
| 4 | Implement rate-limit detection (no retry-storming) | Unit test: rate limit descends without retry |
| 5 | Implement Tier 5 failure handler (session → `failed`) | Unit test: all tiers exhausted → session failed |
| 6 | Wire `agent_runs.tier` recording | Integration test: tier recorded per invocation |
| 7 | Run container-kill failover test | T37.2: primary killed → session completes via fallback |
| 8 | Run full-exhaustion test | T37.3: all tiers fail → session `failed`, reprocessable |

**Atomic Sub-tasks:**
1. LiteLLM config with five-tier ladder definition
2. Router with failover descent and trigger detection
3. Per-tier timeout configuration
4. Rate-limit handling (no retry-storm)
5. Tier 5 failure handler and `agent_runs.tier` recording
6. Integration tests: failover, exhaustion, config flexibility

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Tier 1 timeout | Descent to Tier 2 with 120s budget |
| Tier 3 rate limit | Descent to Tier 4, no retry at Tier 3 |
| Schema invalid at hosted tier | One bounded retry, then failover |
| All tiers exhausted | Mark session `failed`, never `complete` |
| LiteLLM proxy down | Requests fail with explicit error (no silent loss) |
| API key missing for Tier 3 | Skip Tier 3, descend to Tier 4, log warning |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Chain of Responsibility: each tier is a handler in the failover chain
- Strategy pattern: timeout/trigger detection per tier
- Observer pattern: tier recording to `agent_runs`

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case (`llm_router.py`, `failover_handler.py`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- Enum types for tier and trigger classifications

---

### 5. API & Interface Contracts

**LiteLLM Config (`config/litellm.yaml`):**
```yaml
model_list:
  - model_name: tier_1_local
    litellm_params:
      model: vllm/microsoft/Phi-3-mini-3.8B-4bit
      api_base: http://vllm:8000/v1
      timeout: 60
  - model_name: tier_2_cpu
    litellm_params:
      model: llama.cpp/llama-3-7b-4bit
      api_base: http://llamacpp:8080/v1
      timeout: 120
  - model_name: tier_3_openai
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
      timeout: 30
  - model_name: tier_4_cheap
    litellm_params:
      model: together_ai/llama-3-8b-instruct
      api_key: os.environ/TOGETHER_API_KEY
      timeout: 30

router_settings:
  routing_strategy: "simple-shuffle"
  num_retries: 0  # failover is the retry mechanism
  timeout: 60
  allowed_fails: 1
  retry_after: 0  # no retry, immediate failover
```

**Router Interface:**
```python
# src/services/llm/router.py
class LLMRouter:
    async def complete(
        self,
        messages: list[dict],
        agent_id: str,
        prompt_version: str,
        schema: dict | None = None,
    ) -> LLMResponse:
        """Route completion request through failover ladder."""
        ...

    async def _try_tier(
        self, tier: TierConfig, messages: list[dict], timeout: int
    ) -> LLMResponse | None:
        """Attempt completion at a single tier. Returns None on failure."""
        ...
```

**Mock Request/Response:**
```json
// Request
{
  "messages": [
    {"role": "system", "content": "You are a helpful tutor."},
    {"role": "user", "content": "Explain photosynthesis"}
  ],
  "agent_id": "A1",
  "prompt_version": "v2.1"
}

// Response (Tier 1 success)
{
  "content": "Photosynthesis is the process by which plants...",
  "tier_used": "tier_1",
  "model": "phi-3-mini-3.8b-4bit",
  "latency_ms": 1200,
  "tokens_used": 350,
  "failed": false
}

// Response (Tier 5 - all exhausted)
{
  "content": "",
  "tier_used": "tier_5",
  "model": "",
  "latency_ms": 0,
  "tokens_used": 0,
  "failed": true,
  "failure_reason": "All tiers exhausted after http_error at tier_4"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `LITELLM_CONFIG_PATH` | string | Path to LiteLLM config | `config/litellm.yaml` |
| `OPENAI_API_KEY` | string | OpenAI API key for Tier 3 | — |
| `ANTHROPIC_API_KEY` | string | Anthropic API key for Tier 3 | — |
| `TOGETHER_API_KEY` | string | Together.ai key for Tier 4 | — |
| `FIREWORKS_API_KEY` | string | Fireworks key for Tier 4 | — |
| `GROQ_API_KEY` | string | Groq key for Tier 4 | — |
| `LLM_TIMEOUT_T1` | int | Tier 1 timeout (seconds) | `60` |
| `LLM_TIMEOUT_T2` | int | Tier 2 timeout (seconds) | `120` |
| `LLM_TIMEOUT_T3` | int | Tier 3 timeout (seconds) | `30` |
| `LLM_TIMEOUT_T4` | int | Tier 4 timeout (seconds) | `30` |

**Third-Party Integration Contracts:**
- LiteLLM proxy: standard OpenAI-compatible interface
- OpenAI/Anthropic/Together.ai: standard REST API with API key auth

**Version Pins:**
- LiteLLM pinned in `pyproject.toml`
- API SDK versions pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T37.1 | I | `pytest tests/test_llm_router.py::test_failover_triggers -v` | Each trigger condition independently causes descent |
| T37.2 | E | `pytest tests/test_llm_router.py::test_container_kill_failover -v` | Primary model killed mid-flow → session completes via fallback |
| T37.3 | E | `pytest tests/test_llm_router.py::test_all_tiers_exhausted -v` | All tiers fail → session `failed`, never `complete` |
| T37.4 | I | `pytest tests/test_llm_router.py::test_timeout_configurable -v` | Timeout budget is configurable per agent |
| T37.5 | I | `pytest tests/test_llm_router.py::test_tier_recorded -v` | Tier used recorded in `agent_runs.tier` |
| T37.6 | I | `pytest tests/test_llm_router.py::test_rate_limit_no_retry_storm -v` | Rate limit descends without retry-storming |

**Test Case Details (Given/When/Then):**

**T37.1 — Each trigger causes descent**
- **Given:** a router with Tier 1 configured to fail with HTTP 500
- **When:** a completion request is made
- **Then:** the request descends to Tier 2 and succeeds; `RoutingDecision.trigger == "http_error"` is recorded
- Repeat for: timeout, rate_limit, schema_invalid (each independently)

**T37.2 — Container kill failover (AC-8)**
- **Given:** Tier 1 vLLM is serving a multi-turn session
- **When:** the vLLM container is killed mid-flow
- **Then:** the session completes via Tier 2 or higher, `agent_runs.tier` records the fallback tier, session status is `complete`

**T37.3 — All tiers exhausted (AC-9, Tier 5)**
- **Given:** all tiers are configured to fail (mocked)
- **When:** a completion request is made
- **Then:** session is marked `failed` (never `complete`), transcript is retained, session is reprocessable

**T37.4 — Timeout configurable per agent**
- **Given:** agent A1 has timeout 60s and agent A2 has timeout 120s for Tier 1
- **When:** both agents make requests to Tier 1
- **Then:** A1 times out after 60s, A2 times out after 120s

**T37.5 — Tier recorded per invocation**
- **Given:** a router completing a request via Tier 2
- **When:** the request completes
- **Then:** `agent_runs` row has `tier = "tier_2"`

**T37.6 — Rate limit no retry-storm**
- **Given:** Tier 3 returns HTTP 429
- **When:** the router receives the rate limit response
- **Then:** it descends to Tier 4 immediately, with no retry attempts at Tier 3

**Verification Commands:**
```bash
docker compose up -d litellm && \
uv run pytest tests/test_llm_router.py -v -k "S37 or router or failover" && \
uv run mypy --strict src/services/llm/ && \
uv run ruff check src/services/llm/
```

**Exit Criteria:**
- [ ] T37.1 passes — each trigger independently causes descent
- [ ] T37.2 passes — container kill → session completes via fallback (AC-8)
- [ ] T37.3 passes — all tiers exhausted → session `failed`, reprocessable (AC-9)
- [ ] T37.4 passes — timeout configurable per agent
- [ ] T37.5 passes — tier recorded in `agent_runs`
- [ ] T37.6 passes — rate limit descends without retry-storm

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- `num_retries > 0` in LiteLLM causes retry-storm on rate limits — must be set to `0`
- Missing API keys cause silent Tier skip — log warning when tier is skipped due to missing key
- Tier 2 (llama.cpp) CPU inference can be slow — timeout budget of 120s is intentional
- Schema invalid retry must be bounded (exactly 1) or infinite loops possible

**Fallback Instructions:**
- If LiteLLM proxy fails to start: check config YAML syntax, verify all tier endpoints
- If a tier is skipped due to missing API key: log warning, continue descent
- If all tiers fail: ensure transcript is retained, session marked `failed` for reprocessing

**Rollback Procedure:**
- Disable LiteLLM: `docker compose stop litellm`
- Direct vLLM calls bypass the router (for emergency use)
- No database changes — `agent_runs.tier` is nullable

---

### 9. Observability (if applicable)

**Metrics Added:**
- `llm_router_requests_total`: counter (labels: tier, trigger, status)
- `llm_router_failover_total`: counter of failover events (labels: from_tier, to_tier, trigger)
- `llm_router_latency_seconds`: histogram per tier
- `llm_router_tier_5_failures_total`: counter of Tier 5 failures (all exhausted)

**Tracing/Logging:**
- Span: `llm_router.route` with attributes (agent_id, tier_attempted, trigger, latency_ms)
- Log: WARNING on each failover descent
- Log: ERROR on Tier 5 failure (all exhausted)
- Log: INFO on successful completion with tier used

**Alerts:**
- Failover rate > 30% over 5 minutes: investigate Tier 1 health
- Tier 5 failures > 0 in 10 minutes: critical — system-wide model failure
- Rate limit events > 10/hour: review API quotas

---

### 10. Exit Checklist

- [ ] All tests pass (T37.1, T37.2, T37.3, T37.4, T37.5, T37.6)
- [ ] Five-tier ladder defined in `config/litellm.yaml`
- [ ] Container kill does not lose a session (AC-8)
- [ ] All tiers exhausted → session `failed`, never `complete` (AC-9)
- [ ] Tier recorded in `agent_runs` for every invocation
- [ ] Rate-limit handling does not cause retry-storm

# ADR-016: Hybrid LLM Ladder (Local → CPU → Hosted)

## Status
Accepted

## Context
4GB VRAM prevents running capable local LLMs for agents (A1-A6).
Must balance: cost, latency, quality, offline capability.

## Decision
Five-tier LiteLLM ladder (local-first, inverted from v2.0):

| Tier | Provider | Model | Use Case |
|------|----------|-------|----------|
| 1 | Local (vLLM/SGLang) | Phi-3-mini-3.8B-4bit / Qwen2.5-3B-4bit | Default, offline-capable |
| 2 | Local CPU (llama.cpp) | Llama-3-7B-4bit / Mistral-7B-4bit | Fallback when GPU busy/OOM |
| 3 | Hosted API | OpenAI GPT-4o-mini / Anthropic Haiku | Quality-critical, complex prompts |
| 4 | Hosted API (cheap) | Together.ai / Fireworks / Groq | Cost-optimized fallback |
| 5 | **FAIL** | — | Mark session `failed`, enqueue for retry |

**Triggers for descent** (per FR-3.10):
- HTTP error (5xx, 429)
- Timeout (>60s Tier 1, >120s Tier 2, >30s Tier 3/4)
- Schema-invalid output (Pydantic validation fail)
- Rate limit response

**Tier 5 behavior**: Session marked `failed` (never `complete`), fully reprocessable from retained transcript (NFR-R4).

## Consequences
- No single model failure loses a session
- Local-first for privacy/cost, hosted for quality
- Tier 5 is explicit failure, not silent degradation
- Cost attribution per tier via `agent_runs.tier`

## Follow-up
- S36: LLM serving (vLLM for Tier 1)
- S37: LiteLLM router config
- S38: Structured output + validation
- S41+: Agents use ladder transparently

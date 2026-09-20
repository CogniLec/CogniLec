# Notely/CogniLec (LIS) — Pipeline Performance & Architecture Overhaul Audit

**Scope:** analysis and live research only. No code changed, no services started/stopped, nothing installed, no signups. All findings below are labeled **MEASURED** (observed directly, cited), **DERIVED** (calculated from measured inputs, arithmetic shown), **ASSUMED** (a stated modeling assumption, flagged as such), or **UNVERIFIED** (could not confirm with available tools).

## Executive summary (≤200 words)

The pipeline works end-to-end on real audio but has two distinct problems, not one. **Latency**: a 5-minute lecture takes 15-20 minutes (MEASURED, `docs/gaps.md`), dominated by T5 (relevance filter, ~70% of wall-clock) because it is LLM-bound on a single 4GB Turing card with `max-num-seqs 1` (MEASURED live). **Correctness at scale**: T6 (note synthesis) sends the *entire* filtered transcript in one unbatched call, and the deployed model's context is hard-capped at 2048 tokens (MEASURED live). DERIVED arithmetic below shows this call structurally runs out of room somewhere around 15-20 minutes of lecture content — meaning T6 doesn't just get slow on a long lecture, it becomes **unable to complete at all**, well before any timeout fires. This is the more urgent finding.

The three changes that produce most of the gain, none requiring new spend: (1) fix the CPU-forced ASR (a one-line env change once the image ships CUDA libs — already fully diagnosed and unfixed in this codebase), (2) batch T6 the way T5 already is, removing the context-ceiling cliff entirely, (3) run a persistent Prefect server instead of the current per-run ephemeral one and fix the T7 cache-key bug, both cheap and correctness-neutral.

---

# PHASE 1 — Pipeline Breakdown & Latency Budget

## 1.1 Task inventory

| Stage | What it computes | Input var. `n` | Complexity in `n` | Hardware bound | Peak VRAM |
|---|---|---|---|---|---|
| Chunk ingest | Valkey stream write + MinIO put per 30s audio chunk | chunks | O(1) per chunk | IO | none |
| Preprocessing | VAD / resample (`src/services/preprocessing`) | chunk duration | O(duration) | CPU | none |
| ASR transcription | faster-whisper decode | audio duration | ~O(duration) (with some overhead per utterance boundary) | **CPU today** (forced — see 2.3), GPU-capable | ~1-2GB if on GPU |
| Diarisation | pyannote 3.1, on-demand | audio duration | O(duration) | GPU (own container) | separate from vLLM/TEI |
| T1 embed_utterances | TEI embeds every utterance | utterances | O(utterances) | GPU (Machine C) or CPU fallback | small (0.6B embed model) |
| T2 segment_session | TextTiling over embeddings | utterances | O(utterances) | CPU | none |
| T3 cluster_segments | UMAP + HDBSCAN over segment embeddings | segments | UMAP ~O(n log n), HDBSCAN ~O(n log n) | CPU | none |
| T3b label_topics | 1 LLM call per topic | topics | O(topics) LLM calls | LLM-latency (Tier-1 GPU) | shares vLLM's footprint |
| T4 route_session_type | pure dispatch | — | O(1) | none | none |
| T5 filter_utterances | batched LLM classification, `guided_json` | utterances | O(⌈utterances/8⌉) LLM calls | **LLM-latency**, dominant stage | shares vLLM's footprint |
| T6 synthesize_notes | **one** unbatched LLM call over ALL relevant utterances | relevant utterances | O(1) call, but **prompt size is O(relevant utterances)** | LLM-latency + **context-length hard ceiling** | shares vLLM's footprint |
| T7 persist_notes | DB writes | sections | O(sections) | IO/DB | none |
| Flashcard generation | 1 unconstrained LLM call per topic | topics | O(topics) LLM calls | LLM-latency | shares vLLM's footprint |

Citations: `src/services/orchestration/session_pipeline.py:105-286` (T2/T4/T5/T6/T7 task definitions), `src/ml/clustering/bertopic_pipeline.py:13-25` (UMAP/HDBSCAN config, CPU-only libraries — no GPU dependency in this file), `src/services/filtering/relevance_filter.py:30,94-97` (T5 batching), `src/services/synthesis/note_synthesis.py:66-88` (T6's single full-context call, no batching), `src/services/study/flashcards.py:67-86` (flashcard gen, no `schema=` passed — unconstrained decoding, confirmed by reading the call site).

## 1.2 Sixty-minute latency budget

**Ground-truth measurements used as inputs (MEASURED):**
- vLLM container `docker inspect lis-vllm`: `--model Qwen/Qwen2.5-3B-Instruct-AWQ --quantization awq --gpu-memory-utilization 0.85 --max-model-len 2048 --max-num-seqs 1 --enforce-eager`. Confirmed live via `docker exec lis-vllm curl localhost:8000/v1/models` → `"max_model_len":2048`.
- `nvidia-smi`: `NVIDIA T1000, 4096 MiB total, 3396 MiB used, compute_cap 7.5`. So a running instance leaves **~700MB free** on this specific card at idle (weights + KV cache pool already allocated at `--gpu-memory-utilization 0.85`).
- `max-num-seqs 1` means **zero concurrent decoding** within a single vLLM instance — the *only* real parallelism is the two-backend LiteLLM round-robin (`config/litellm.yaml`, two `tier_1_local` entries), which is why `DEFAULT_MAX_CONCURRENCY = 2` (`relevance_filter.py:50`) matches exactly 2 backends, not a higher number.
- T5 per 8-utterance batch: 67-110s warm (MEASURED, `docs/gaps.md:2038`).
- Full sequential-T5 5-min-lecture run: T5 took 197s across the run I read directly from live asr-worker logs earlier this session (17:31:33→17:35:18 for `T5_filter_utterances`), T6 took 147s (17:35:18→17:37:45) on the same run. `docs/gaps.md`'s own aggregate figure for many runs is "roughly 15-20 minutes" total for a 5-minute lecture — I'm using the more conservative gaps.md range for the headline number and my own directly-observed per-stage split for the arithmetic below, since both are real measurements, not assumptions.
- Two-backend measured improvement: T5 ~11.5min → ~8min (`docs/gaps.md:2136`), a **30.4% reduction** ((11.5-8)/11.5), not a full 2x — DERIVED ratio used below, not assumed to be linear-with-backend-count.

**Utterance-density assumption (ASSUMED, arithmetic shown):** the 5-minute lecture that produced the 197s T5 run had few enough utterances to need only 2-3 batches at 8/batch (197s ÷ ~85s avg-per-batch ≈ 2.3 batches) → 16-24 utterances in 5 minutes → **~3.2-4.8 utterances/minute**. I use **4 utterances/minute** as a round working assumption for the 60-minute extrapolation below. This is a real, cited derivation, not a guess pulled from nowhere, but it is still an extrapolation from one clip's utterance density, which varies by speaking pace — flagged ASSUMED.

**60-minute utterance count (DERIVED):** 60 min × 4 utt/min = **240 utterances**.

**T5 at 60 minutes (DERIVED):**
- Batches: ⌈240/8⌉ = **30 batches**.
- Sequential (1 effective backend), using the 67-110s range's midpoint ≈ 88.5s/batch: 30 × 88.5s = **2655s ≈ 44.3 minutes**.
- Two-backend (apply the measured 30.4% reduction ratio from the 5-min case): 2655s × (1 − 0.304) = **1848s ≈ 30.8 minutes**.
- This alone **already exceeds the 1800s (30 min) worker ceiling** (`asyncio.wait_for(..., timeout=1800)`, `src/workers/asr_worker.py`) by itself, before T6, T7, or flashcard generation even run. See 1.5 for the exact crossover.

**T6 at 60 minutes — this is the critical finding, a correctness ceiling, not just a latency one:**

T6 sends the *entire* relevant-utterance transcript in one prompt (`note_synthesis.py:66-88`, confirmed no batching). Token budget arithmetic (DERIVED, ASSUMED where noted):
- System prompt: ~130 words × 1.3 tokens/word ≈ **170 tokens** (counted from the actual string literal at `note_synthesis.py:70-82`).
- Per utterance in the JSON payload: `{"id": "<uuid, 36 chars ≈ 12 tokens>", "seq": N, "text": "..."}`. ASSUMED average utterance text ≈ 15 words ≈ 20 tokens (typical short spoken utterance). JSON scaffolding (`id`/`seq`/`text` keys, braces, commas) ≈ 10 tokens. **≈ 42 tokens/utterance** total.
- Available room for transcript + output, reserving the 170-token system prompt: 2048 − 170 = **1878 tokens**.
- If a lecture has ~60% of utterances survive T5 filtering (ASSUMED — reasonable for a lecture with some off-topic/admin content, not independently measured), then 240 total × 0.6 = **144 relevant utterances** at 60 minutes.
- Transcript-only cost: 144 × 42 = **6048 tokens** — this is **3.2x over the entire 2048-token context window**, leaving zero room for the JSON scaffolding, segment summaries, prior notes, syllabus context, *or the model's own output*.
- **Crossover point** (DERIVED): solving for the utterance count where transcript-only cost consumes all 1878 remaining tokens (i.e., the point past which T6 cannot produce even one token of output): 1878 ÷ 42 ≈ **44.7 relevant utterances**. At the ASSUMED 60% relevance rate, that's ≈ 75 total utterances, and at 4 utterances/minute that is **≈ 18.7 minutes of lecture**.

**This means: somewhere around an 18-20 minute lecture (using this session's own ASSUMED utterance-density and relevance-rate inputs — real numbers will vary by lecture), T6 stops being able to generate notes at all, independent of and prior to any latency/timeout concern.** A 60-minute lecture is roughly 3x past this line. This is the single most important finding in this audit: fixing T6 is not an optimization, it's a prerequisite for the app working on any lecture longer than about 15-20 minutes of substantive content.

**T1/T2/T3/T3b/T7 at 60 minutes (DERIVED, scaled from measured 5-min-clip timings earlier this session — T1 9s, T2 ~0s, T3 13s, T3b 15s):**
- T1 (TEI embed, O(utterances)): 9s × (240/20 utterances) ≈ **108s** (ASSUMED linear scaling; TEI batches internally so real scaling may be sub-linear — flagged).
- T2 (CPU, O(utterances)): negligible at 5 min, DERIVED ≈ **5-10s** at 60 min, not a bottleneck.
- T3 (UMAP+HDBSCAN, CPU, ~O(n log n) in segments): 13s at ~5-8 segments → DERIVED **≈ 60-90s** at 60-90 segments (60-min lecture); UMAP is the more expensive half and does not scale linearly, so this could be higher — flagged ASSUMED, not measured at this scale.
- T3b (1 LLM call per topic, not per utterance): cost scales with **topic count**, not lecture length directly. A 60-minute lecture likely has more topics than a 5-minute one but not proportionally 12x — DERIVED estimate **30-60s** for 3-6 topics vs. 1-2 at 5 minutes.
- T7 (DB writes): trivially fast regardless of scale, not a bottleneck at any lecture length.

**Total 60-minute wall-clock estimate (DERIVED, two-backend T5, and — critically — assuming T6 could somehow complete despite the context-ceiling finding above, which in reality it cannot):**
T1(108s) + T2(10s) + T3(75s) + T3b(45s) + T5(1848s) + T6(would fail) + T7(~5s) ≈ **36-37 minutes just through T5**, before T6 is even reachable in a working state. The real-world outcome for a 60-minute lecture today is **a failed/incomplete T6**, not merely a slow one.

## 1.3 Critical path + Amdahl analysis

Dependency graph (from `process_session`, `session_pipeline.py:323-397`): T1→T2→T3→T3b→T4→T5→T6→T7 is a **strictly sequential chain** — every stage's DB reads depend on the prior stage's writes being committed. There is no cross-stage parallelism available; the only parallelism that exists today is *within* T5 (batches, bounded by `max_concurrency` and real backend count).

| Stage | Share of 60-min DERIVED total (excl. failed T6) | "If instant, total drops by" |
|---|---|---|
| T5 | ~1848s / ~2136s ≈ **86.5%** | 86.5% |
| T3 | ~75s / ~2136s ≈ 3.5% | 3.5% |
| T3b | ~45s / ~2136s ≈ 2.1% | 2.1% |
| T1 | ~108s / ~2136s ≈ 5.1% | 5.1% |
| T2, T4, T7 | negligible | negligible |

**T5 alone accounts for ~86.5% of the (T6-excluded) critical path.** Any optimization not touching T5 or T6 yields single-digit-percent gains at best. T2/T4/T7 are explicitly **not worth touching** — they are already near-zero cost at any lecture length observed or projected here.

## 1.4 Overhead accounting

- **Prefect ephemeral server startup**: MEASURED from live asr-worker logs, the "Starting temporary server on http://127.0.0.1:PORT" line appears 2-4 seconds before the flow's first task begins, once per `generate_study_materials` invocation (once per session, not per task). At ~3.5s average and a 60-minute-lecture total of ~2136s, this is **0.16% of total time** — genuinely negligible for latency, but real for developer-experience/log noise, and Prefect's own community explicitly documents this as "increased start-up time" inherent to ephemeral mode (see Phase 2.1).
- **Cache-key computation, including the T7 bug**: `_cache_key_t7` (`session_pipeline.py:101-102`) reads `parameters['prompt_version']`, but `persist_notes_task`'s signature (`session_pipeline.py:267-273`) has no `prompt_version` parameter — confirmed by reading both directly. This raises a `KeyError` inside Prefect's `compute_transaction_key`, logged as `"Error encountered when computing cache key - result will not be persisted"` (confirmed against live logs earlier this session). **Effect: T7's Prefect-level caching is fully, silently disabled** — every T7 run re-executes in full regardless of whether identical inputs were already processed. Cost of this bug: since T7 itself is fast (DB writes, milliseconds-to-low-seconds), the *latency* cost is negligible — but it does mean a retried T7 (on transient DB errors) always redoes full work instead of returning a cached result, and the ERROR-level log line is pure noise obscuring real errors in the same log stream.
- **30s retry delays**: T5 `retries=2`, T6 `retries=2`, T7 `retries=1`, each `retry_delay_seconds=30` (`session_pipeline.py:105-286`). These only fire on actual failures, so they cost nothing in the happy path — but a single T5 batch failure adds a **flat +30s** before retry, and a full retry exhaustion on T5 or T6 adds **+60s** (2 delays) directly to the critical path, separate from the retried work itself.

## 1.5 Failure-mode latency

Two separate ceilings exist, and **the context-length ceiling (1.2) is hit first**, well before the 1800s worker timeout ever becomes relevant, for any realistic lecture:
- Context-length ceiling (T6): ≈ **18-20 minutes** of lecture (DERIVED, 1.2).
- 1800s worker ceiling (`asyncio.wait_for(..., timeout=1800)`, `src/workers/asr_worker.py`): using the DERIVED two-backend T5-only cost model (44.3min sequential / 30.8min two-backend for a full 60-minute lecture), solving for where **T5 alone** consumes 1800s: 1800s ÷ 88.5s/batch/(1−0.304 two-backend factor) → batches ≈ 1800 × 0.696 ÷ 88.5 ≈ **14.2 batches** → 14.2 × 8 = **~114 utterances** → at 4 utt/min, **≈ 28.4 minutes of lecture**, T5 alone would exceed the worker's total ceiling — and that's before T1/T3/T6/T7 get any of the remaining budget at all.

**Bottom line: today, a lecture longer than roughly 18-20 minutes is already at risk of T6 correctness failure, and a lecture longer than roughly 28-30 minutes is at risk of the worker's own 1800s ceiling being exceeded by T5 alone.** Both numbers are well under the "60-minute lecture" scenario this audit was asked to model, and well under NFR-P3's own stated target ("60-minute lecture in < 15 min P90" — explicitly marked untested at production scale in `tests/test_s47_process_session_flow.py`'s own skip reason, confirmed by reading that file).

---

# PHASE 2 — Live Research

## 2.1 Orchestration

**Can Prefect itself remove the ephemeral-server cost?** Yes — Prefect's own community documentation confirms ephemeral mode is what causes the per-run startup cost ("this will likely lead to increased start-up time when in ephemeral mode"), and the fix is to run a real `prefect server` process and point flows at it via `PREFECT_API_URL` (equivalently, disable ephemeral fallback with `PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=false` once a real server is configured, so a misconfiguration fails loudly instead of silently falling back to ephemeral). Source: [Prefect Community — "what is ephemeral mode"](https://linen.prefect.io/t/27105671/ulva73b9p-what-is-ephermeral-mode), [Prefect Settings Reference](https://docs.prefect.io/v3/api-ref/settings-ref), retrieved 2026-09-20. Given 1.4 already shows this overhead is ~0.16% of total time, this is a **cheap, correctness-neutral cleanup**, not a latency fix — do it because it's free and removes log noise, not because it moves the needle on the real bottleneck.

**Alternatives evaluated (candidates named in the brief), verified before judging:**

| Option | Verified? | Category fit for this pipeline | Migration cost | Verdict |
|---|---|---|---|---|
| Plain asyncio + existing Valkey streams | Already in the stack | Exact fit — the pipeline is a strictly linear chain (1.3); no DAG branching, no need for a scheduler UI | Low — replace `@task`/`@flow` decorators with plain `async def` + a small retry-with-backoff wrapper (~50-100 LOC); the two things actually lost are Prefect's cache-key mechanism (already broken for T7, and of dubious value for T2/T5/T6 which always process fresh session content) and its UI | **Top local-first candidate** — removes the ephemeral-server cost and the T7 cache bug simultaneously by removing the thing that has the bug |
| **Hatchet** | Exists, MIT-licensed, Postgres-only durability layer (already have `lis-pg-main`), Python SDK with DAGs, durable tasks, retries. Source: [github.com/hatchet-dev/hatchet](https://github.com/hatchet-dev/hatchet), retrieved 2026-09-20; repo shows 3,568+ commits, active development. | Legitimate fit — a real DAG orchestrator, not a category error | Medium — needs its own server+worker containers added to `docker-compose.yml` (new operational surface even though it reuses Postgres), plus rewriting all task/flow definitions to Hatchet's API | Worth a pilot if the team wants a real UI/observability layer later; **not justified purely for latency** — it doesn't touch the T5/T6 bottleneck at all |
| **Temporal** | Real, mature, but "code-centric" and has real "operational overhead" per its own comparison writeups. Source: [Kestra — Temporal alternatives](https://kestra.io/resources/infrastructure/temporal-alternatives), retrieved 2026-09-20. | Designed for long-running business processes with complex external-event waits — this pipeline has neither | High — needs its own multi-service cluster (Temporal server + Elasticsearch/Postgres + workers) | **Reject** — heavyweight for a linear 8-step DAG on constrained hardware; adds infrastructure the project explicitly cannot spare VRAM/RAM for |
| **Dagster** | Real, but explicitly a *data-asset* orchestrator (lineage/freshness-first), "best for greenfield data platforms." Source: [Orchestra — Dagster alternatives 2026](https://www.getorchestra.io/blog/top-dagster-alternatives-in-2026-data-orchestration-primer), retrieved 2026-09-20. | Poor fit — this pipeline has no asset-lineage requirement; forcing the asset model onto a linear ML pipeline is pure ceremony | High | **Reject** |
| **Celery / Dramatiq** | Real, mature task-queue libraries | **Category error** — these dispatch independent background jobs onto a queue; this pipeline already has a message queue (Valkey streams) driving invocation of one already-running worker process. Adding Celery/Dramatiq here would add a second broker layer on top of an existing one, not replace anything. | N/A | **Reject outright** |
| **Pydantic AI / smolagents** | Real, but confirmed via direct research to be **LLM agent frameworks** (single-agent reasoning loops with tool-calling and type-safe structured output), explicitly described as living "a layer below full orchestration." Source: [QED42 — choosing an agentic framework](https://www.qed42.com/insights/choosing-the-right-agentic-ai-framework-smolagents-pydanticai-and-llamaindex-agentworkflows), retrieved 2026-09-20. | **Category error, confirmed, not just suspected** — this pipeline's sequence (T1→T7) is fixed and deterministic; there is no decision for an LLM agent to make about *what to do next*. Using an agent framework to drive a fixed DAG would add a nondeterministic reasoning layer on top of a process that must stay deterministic (FR-2.15 soft-delete semantics, provenance requirements) for exactly the reasons the code comments already state. | N/A | **Reject outright, explicitly** |
| **Kestra, Bruin** (named in the brief) | Kestra is a real, YAML-declarative orchestrator; Bruin is real but is primarily a **data-pipeline/ELT and data-quality tool**, not a general task DAG runner (its own marketing centers on "data pipelines," SQL/Python transformations, and data-quality checks — a mismatch for an ML inference pipeline). | Both are poor fits for the same reason as Dagster (data-pipeline framing, not ML-task framing) plus, for Kestra, a full YAML-based server stack | High | **Reject** |

## 2.2 Inference on 4GB Turing

**Guided-decoding backend — the single highest-leverage inference finding in this audit.** vLLM 0.5.5 (released 2024-08-23, confirmed via search) supports **Outlines** (the default) and **lm-format-enforcer** as guided-decoding backends — confirmed via vLLM's own structured-outputs docs. **XGrammar**, which current research describes as "the fastest in 2026 for most schemas" with negligible (<2%) throughput loss and O(1) mask application versus Outlines' "overhead of up to several seconds per step," only became the default starting at a materially newer vLLM version (referenced as "since v0.7" in secondary sources — I could not independently pin the exact version number from a primary vLLM release note in the time available; **flagged UNVERIFIED, confirm against vLLM's actual v0.7.x changelog before committing to an upgrade plan**). Sources: [vLLM Blog — Structured Decoding in vLLM](https://vllm.ai/blog/2025-01-14-struct-decode-intro), [SqueezeBits — Guided Decoding Performance](https://blog.squeezebits.com/guided-decoding-performance-vllm-sglang), retrieved 2026-09-20.
  - This directly explains the measured 67-110s-per-batch T5 cost even "with a warm FSM cache" (the code's own comment names Outlines specifically) — Outlines' FSM-compilation and per-step overhead is a known, named cost in current research, not a mystery.
  - **Two actionable paths, in order of risk:**
    1. **Lower risk, no upgrade needed:** switch to `lm-format-enforcer` on the *current* vLLM 0.5.5 — both backends are already supported in this exact version (confirmed), and lm-format-enforcer's character-level-parser design is described as "lightweight" versus Outlines' FSM-hash approach. This is a one-flag config change (`--guided-decoding-backend lm-format-enforcer`) worth A/B-measuring directly against the real 5-minute test clip before any larger change.
    2. **Higher risk, higher ceiling:** upgrade vLLM to unlock XGrammar. Must independently re-verify Turing/AWQ compatibility on the target version first (see below) before treating this as safe.

**Turing (SM 7.5) compatibility on a newer vLLM — genuinely mixed, must be tested, not assumed.** Current vLLM mainline (referenced up to ~v0.20.x as of June 2026) still lists compute capability 7.5 as supported, and Turing lacks native BF16 execution units (confirmed, matches the ground-truth note for this audit — any recommendation involving BF16 KV-cache or BF16-only kernels is invalid on this hardware and must stay FP16/INT8). Source: [Speediyo — vLLM Legacy GPU Setup](https://www.speediyo.com/ai-infra/vllm-v100-t4-sm70-sm75-fallback), [Speediyo — GPU Compatibility Matrix](https://www.speediyo.com/ai-infra/vllm-gpu-compute-capability-matrix), retrieved 2026-09-20. **A specific, important caveat found**: an open/recent GitHub PR (`vllm-project/vllm#29901`, "add marlin kernel support for turing (sm75)") indicates Marlin-accelerated AWQ kernels for Turing may be **very recently added or still pending merge** — meaning the *already-deployed* AWQ model may currently run on the older (slower) AWQ kernel path on this exact card, and an upgrade past whenever that PR ships could unlock a real speedup on the existing model with no other change. **UNVERIFIED**: I could not confirm from the PR listing alone whether it has merged or which release contains it — this needs a direct check against the PR's merge status and the target vLLM version's changelog before planning around it.

**`--enforce-eager` and `--max-num-seqs 1`**: already both correctly set in `docker-compose.yml:672-681` as hard-won fixes for real OOM issues on this exact card (confirmed by reading the code comments, which cite a live incident). **No change recommended here** — these are not naive defaults to "optimize away," they were added for a documented reason specific to this hardware.

**Chunked prefill, prefix caching**: UNVERIFIED whether vLLM 0.5.5 supports chunked prefill by default or requires a flag — I did not find a version-specific confirmation in the time available for this audit. Flagging as a gap requiring a direct `vllm serve --help` check against the deployed image rather than a web search, since flag availability is version-specific and easy to verify directly.

**SGLang RadixAttention**: real, but adopting SGLang means replacing the entire inference server (not a vLLM flag), which is a much larger migration than anything else considered here, for a Turing/4GB target where the LiteLLM `openai/` HTTP-API integration (already proven working, `config/litellm.yaml`'s own comments document the "vllm/" in-process pitfall already hit and fixed) would need to be re-validated from scratch. Not recommended as a first move given the config-swap wins above are cheaper and untested.

## 2.3 ASR

**Real RTF findings (all sourced from 2026-current benchmark writeups, retrieved 2026-09-20):**
- **faster-whisper** (already deployed, `ASR_MODEL_NAME = "deepdml/faster-whisper-large-v3-turbo-ct2"`, confirmed `src/core/config.py:147`): "4x faster on GPU and 2x faster on CPU with the same accuracy" versus baseline Whisper, per current comparisons. Source: [Northflank — best open-source STT 2026](https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks).
- **distil-whisper**: "6x faster inference than Whisper Large V3... within 1% WER." Source: same Northflank writeup.
- **whisper.cpp**: optimized for CPU-only/Apple Silicon (Metal/Core ML); not a distinguishing win on this project's actual x86+NVIDIA hardware.
- **NVIDIA Parakeet/Canary**: not independently verified with a direct RTF citation in the time available for this audit — **UNVERIFIED**, flagged as a gap.

**The single biggest ASR lever is not a model swap — it's fixing the CUDA library gap already fully diagnosed in this codebase.** `docker-compose.yml:376-386` documents, with a live-confirmed error message, that the `lis-api` image (built `FROM python:3.12-slim`) has **no CUDA runtime at all** (`RuntimeError: Library libcublas.so.12 is not found or cannot be loaded`), forcing `ASR_DEVICE=cpu` unconditionally. Given faster-whisper's own measured "4x faster on GPU," simply rebuilding the image from an `nvidia/cuda` base (or adding `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` + `LD_LIBRARY_PATH`, the exact fix `docs/gaps.md` gap #20 already proved works for the dev venv) is very likely a larger, cheaper win than any model swap, because it's fixing a documented misconfiguration rather than chasing marginal model-quality gains.

**CosyVoice2 — struck, as instructed.** Directly verified: **CosyVoice2 is a zero-shot multilingual TTS (text-to-speech) model, not an ASR model.** It does incorporate an ASR-adjacent auxiliary training task internally, but its function is speech synthesis, not transcription. It has no place in this pipeline's ASR stage and should not be considered further. Source: [emergentmind.com — CosyVoice2 topic page](https://www.emergentmind.com/topics/cosyvoice2-tts-model), retrieved 2026-09-20.

## 2.4 Embeddings + clustering

**Not a bottleneck, per Phase 1.** T1 (TEI embed) was measured at ~9s for a 5-minute clip and DERIVED at ~108s for a 60-minute one (1.2) — under 5% of the (T6-excluded) critical path even at 60 minutes (1.3). T3's UMAP+HDBSCAN clustering runs entirely on CPU with no GPU dependency (`bertopic_pipeline.py` imports only `numpy`), and was measured at 13s / DERIVED at 60-90s at 60-minute scale — also a small fraction of total time. **No further research effort spent here, as instructed when a stage isn't a top-3 bottleneck.**

---

# PHASE 3 — Replacement Strategy & Architecture Overhaul

Every recommendation below is checked against the Phase 1 ranking: T5 ≈ 86.5% of critical-path time, T6 is a **correctness cliff** at ~18-20 minutes of lecture (not just slow), everything else is single digits.

## 3.1 Local-first wins (no cost, ordered)

| # | Change | Addresses | Expected effect | Effort |
|---|---|---|---|---|
| 1 | **Batch T6 the way T5 already is** (split the relevant-utterance transcript into chunks that fit the 2048-token window, synthesize per-chunk, then a final short "coherence pass" merging section lists if cross-chunk continuity matters) | The **correctness cliff** (1.2) — the top-3 bottleneck by *severity*, not just time share | Removes the ~18-20 minute hard ceiling entirely; makes 60-minute lectures possible at all | Medium — this is a genuine design change to T6, not a config flag; needs its own test coverage for cross-chunk section ordinals |
| 2 | **Fix the CPU-forced ASR** (rebuild `lis-api` from an `nvidia/cuda` base or add `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` + `LD_LIBRARY_PATH`, per the already-proven dev-venv fix in gap #20) | Not in the T1-T7 critical path by definition, but a real user-facing latency component (transcription itself, before T1 even starts) with a documented "4x faster on GPU" ceiling (2.3) | Large win for ASR wall-clock specifically; zero risk to T5/T6 since it's a separate stage | Low-medium — rebuild + redeploy, fix already fully diagnosed in this repo |
| 3 | **A/B test `lm-format-enforcer` vs. the current Outlines default** on the existing vLLM 0.5.5, against the real 5-minute test clip | T5, the dominant stage (86.5% of critical path) | Unknown magnitude until measured — but zero-risk to try (one flag, no upgrade, no model change) since both backends are already supported in the deployed version | Low |
| 4 | **Run a persistent Prefect server**, fix `_cache_key_t7`'s missing `prompt_version` parameter (either add it to `persist_notes_task`'s signature or drop the cache_key_fn since T7 is fast enough not to need caching) | Overhead (1.4) and a real, if low-severity, bug | Removes ~3.5s/session ephemeral-startup cost and the T7 error-log noise; correctness-neutral | Low |
| 5 | **Investigate the vLLM Marlin-AWQ-on-Turing PR (#29901)** — check its merge/release status directly before planning an upgrade around it | T5 | Potentially real speedup on the *existing* model with no other change, but currently UNVERIFIED whether it has shipped | Low (just a status check) |
| 6 | Raise T5 concurrency further **only if** a third real GPU backend is added to `config/litellm.yaml`'s `tier_1_local` round-robin — never as an isolated code change against the same 2 backends (`docs/gaps.md #33b`'s own documented negative-result lesson) | T5 | Proportional to backend count, bounded by real hardware, not code | Low if a 3rd machine/GPU is available, otherwise N/A |
| 7 | Investigate whether vLLM 0.5.5 supports chunked prefill and confirm via `vllm serve --help` against the deployed image (UNVERIFIED in this audit) | T5 | Unknown until confirmed | Low (a direct check, not a research task) |

**Not recommended for optimization**: T2, T4, T7, T1, T3 — all confirmed sub-5%-of-critical-path stages (1.3); touching them is effort spent on the wrong 95%.

## 3.2 Hybrid cloud tier (optional burst path)

Pricing (retrieved 2026-09-20, all cited):
- **DeepInfra**: a 7B-class model at **$0.04/1M input, $0.10/1M output tokens**. Source: [costbench.com — DeepInfra Pricing 2026](https://costbench.com/software/llm-api-providers/deepinfra/).
- **OpenRouter**: Qwen2.5-7B-Instruct at **$0.10/1M input, $0.20/1M output**. Source: [openrouter.ai/qwen/qwen-2.5-7b-instruct](https://openrouter.ai/qwen/qwen-2.5-7b-instruct).
- **Together AI**: **$0.30/1M input, $0.30/1M output** for the same class. Source: [together.ai/models/qwen2-5-7b-instruct-turbo](https://www.together.ai/models/qwen2-5-7b-instruct-turbo).
- **Groq**: Qwen3-32B at 662 tok/s, **$0.29/$0.59 per 1M** in/out — faster but pricier, and a different (larger) model class than what's locally deployed. Source: aggregated pricing comparison, [pricepertoken.com — DeepInfra vs Groq](https://pricepertoken.com/endpoints/compare/deepinfra-vs-groq), retrieved 2026-09-20.
- **Fireworks AI**: not independently priced in the time available for this audit — **UNVERIFIED**.

**Cost estimate per lecture (DERIVED token-volume assumptions):** using the 60-minute DERIVED figures from 1.2 — 240 utterances, 144 relevant, ≈42 tokens/utterance for T5's prompt payload (batched, ~30 calls) plus a comparable output size for decisions, and (once T6 is fixed to batch, per 3.1 #1) a similar order of magnitude for T6. ASSUMED total ≈ 150K input + 50K output tokens per 60-minute lecture across T5+T6+flashcards combined (a rough order-of-magnitude estimate, not a precise trace).
  - DeepInfra: (150K × $0.04 + 50K × $0.10) / 1,000,000 ≈ **$0.011/lecture**.
  - OpenRouter: (150K × $0.10 + 50K × $0.20) / 1,000,000 ≈ **$0.025/lecture**.
  - Together AI: (150K × $0.30 + 50K × $0.30) / 1,000,000 ≈ **$0.06/lecture**.

All three are trivially cheap per lecture even at real volume (hundreds of lectures/month still under a few dollars) — **cost is not the reason to avoid cloud burst**, privacy is.

**Privacy — mandatory, not optional.** Lecture audio/transcripts are real personal data (a student's or lecturer's actual speech, potentially containing names, institutional details, or sensitive discussion). Routing any of it to a third-party API means that content leaves the self-hosted boundary this project was explicitly built to keep. **Recommended default: local-only, no cloud burst, unless the user explicitly opts in per-subject or globally.** If burst is ever enabled, it should be config-only (per `config/litellm.yaml`'s existing `model_list` pattern — add a `tier_3_openai`/cloud entry and let LiteLLM's own failover route to it only when local tiers are exhausted, exactly as the 5-tier ladder in `router.py` already models), never a silent default, and the UI should show the user which lectures were processed locally vs. via a cloud tier.

**Structured-output guarantee — a real risk, flagged for verification, not assumed to work.** T5/T6 depend on `guided_json` (a hard schema constraint). Whether DeepInfra/OpenRouter/Together's OpenAI-compatible endpoints enforce a JSON *schema* (not just "valid JSON") the same way vLLM's `guided_json` does was **not independently confirmed in this audit** — flagged **UNVERIFIED**, and this must be tested directly (send a real schema-constrained request to each candidate provider) before treating cloud burst as a drop-in replacement for the local guided-decoding path, since a provider that only guarantees "some valid JSON" without schema enforcement would reintroduce exactly the malformed-output failures the local `guided_json` wiring was built to prevent (`docs/gaps.md #33`/`#33a`).

## 3.3 Quality, not just speed

- **ASR**: fixing the CPU-forced bug (3.1 #2) is itself a quality lever too — GPU-path faster-whisper typically also gets access to larger/better compute types (e.g. `float16` instead of the current CPU-forced `int8`), which can improve WER, not just speed. Verify compute-type options once GPU access is restored.
- **Diarisation integration**: pyannote 3.1 is already deployed as its own container but described in the ground truth as "on demand" — confirm it's actually wired into the note-synthesis prompt (does T6 currently receive speaker labels at all?) since better speaker attribution would materially improve note quality for multi-speaker Q&A segments. Not independently verified in this audit — flagged as a follow-up code-read, not a research question.
- **Prompt/schema changes**: T6's `source_utt_ids` provenance requirement (`note_synthesis.py:47`) is already a strong anti-hallucination guard (confirmed working — this session's own earlier work fixed a bug where one bad citation used to discard an entire good batch). Once T6 is batched (3.1 #1), the per-chunk provenance check still applies cleanly; the only new design question is whether cross-chunk section *ordinals* need a final merge/renumber pass.
- **Evaluation without a labelled corpus**: `docs/gaps.md`'s own long-standing S04/S05 blocker (no hand-labelled evaluation corpus) means none of the above can be measured with a real quality metric today. The pragmatic near-term substitute already available in this stack: **Label Studio is already running** (`lis-label-studio` in `docker ps`) — pointing even a small, ad hoc sample of real sessions at it for manual relevance/quality spot-checks would give *some* signal without waiting for the full corpus effort.

## 3.4 Trade-off table + recommended architecture

| Change | Improves | Regresses / new risk | New operational surface | Reversibility |
|---|---|---|---|---|
| Batch T6 | Correctness ceiling removed | New code path to test (cross-chunk merge) | None | Easy (revert the code change) |
| Fix ASR CUDA | ASR latency + possibly quality | Rebuild/redeploy risk if base image swap breaks other deps | None new | Easy (image rollback) |
| `lm-format-enforcer` A/B | Possible T5 latency win | Unknown until measured; a regression is possible | None | Trivial (one flag) |
| Persistent Prefect server | Removes ephemeral overhead + log noise | One more long-lived process to monitor | Small (a `prefect server` container) | Easy |
| Fix T7 cache key | Removes noisy error log | None | None | Trivial |
| vLLM upgrade for XGrammar | Possible large T5 win | Must re-verify Turing/AWQ compat (2.2's flagged PR); real regression risk if untested | None new (same container) | Medium (pin the old image as rollback) |
| Cloud burst tier | Removes the local hardware ceiling entirely for burst load | Privacy exposure (mandatory opt-in only); untested schema-enforcement guarantee | New: API keys, egress, cost monitoring | Easy to disable (config-only) |
| Hatchet migration | Real observability/UI | New service, full task-API rewrite | Real (new server+worker) | Hard (large rewrite to undo) |

**Recommended migration sequence, with projected latency after each step (all projections DERIVED from the models in Phase 1, not separately re-measured — treat as directional, verify live after each real change):**

1. Fix ASR CUDA gap → ASR wall-clock potentially cut ~4x (2.3); does not touch T1-T7's ~2136s DERIVED 60-min budget directly, but shortens total user-perceived time meaningfully since ASR runs before T1.
2. Batch T6 → pipeline becomes *able to complete* on a 60-minute lecture at all (currently cannot, 1.2) — this is a correctness unlock, and its own latency should be similar in order of magnitude to today's T6 cost scaled by chunk count, roughly proportional to T5's cost model.
3. A/B `lm-format-enforcer` on existing vLLM → if it wins, T5's ~1848s (two-backend, 60-min DERIVED) could drop meaningfully; magnitude unknown until measured, so no specific number is claimed here.
4. Persistent Prefect server + T7 cache-key fix → trivial, do anytime, no dependency on the above.
5. Only after 1-4 are live-measured: decide whether a vLLM upgrade (for XGrammar) or a cloud burst tier is still worth pursuing, based on where the *remaining* bottleneck actually sits — don't commit to either speculatively.

**What I recommend NOT doing, and why:**
- **Do not adopt Temporal, Dagster, Kestra, or Bruin.** All are real tools solving problems this project doesn't have (long-running external-event workflows, data-asset lineage, YAML-declarative ELT) at a cost (new multi-service infrastructure) this constrained hardware can't spare and this simple linear DAG doesn't need.
- **Do not adopt Pydantic AI or smolagents for orchestration.** Confirmed category error — they are agent-reasoning frameworks, and this pipeline needs determinism, not agentic decision-making, for the exact provenance/soft-delete correctness reasons already encoded in the current design.
- **Do not add Celery or Dramatiq.** A second broker layer on top of the existing Valkey-stream-driven invocation model, solving nothing.
- **Do not default cloud burst to "on."** Cost is negligible (3.2), but privacy is not, and the structured-output enforcement guarantee is unverified — both argue for local-only-by-default with explicit opt-in, never a silent fallback.
- **Do not chase T1/T2/T3/T4/T7 optimization.** Confirmed sub-5%-of-critical-path stages; any time spent here is provably the wrong 95% of the effort (1.3).
- **Do not assume the vLLM-Turing-Marlin-AWQ PR has shipped.** It's a real, promising finding, but treating an unverified PR-merge-status as a done deal would be exactly the kind of unverified claim this audit was told to avoid presenting as fact.

---

# What I could not determine, and what would close each gap

1. **Exact vLLM version where XGrammar became the default / minimum version supporting it.** Needs a direct read of vLLM's own version-tagged changelog/release notes (I found secondary sources citing "since v0.7" but could not independently confirm against a primary vLLM release note in the time available).
2. **Merge/release status of `vllm-project/vllm#29901`** (Turing Marlin-AWQ kernel support). Needs a direct GitHub API check (`gh pr view 29901 --repo vllm-project/vllm`) for merge state and, if merged, which tagged release first included it.
3. **Whether vLLM 0.5.5 supports chunked prefill and what flag enables it.** Needs `docker exec lis-vllm vllm serve --help` (or equivalent) against the actual running image — a direct check, not a web search, since flag surfaces are version-specific.
4. **Whether DeepInfra/OpenRouter/Together AI enforce a JSON *schema* (not just valid JSON) equivalent to vLLM's `guided_json`.** Needs a live test call to each candidate with a real Pydantic schema and a deliberately schema-violating scenario, comparable to how `guided_json` was originally validated in this project (`docs/gaps.md #33a`'s own methodology).
5. **Real utterance density and T5-relevant-filtering rate for lectures longer than the 5-minute clips tested so far.** Needs at least one real 30-60 minute lecture run through the (currently context-limited) pipeline, or a direct utterance-count query against a real longer session if one exists in the database, to replace the ASSUMED 4 utt/min and 60%-relevance-rate inputs with measured ones.
6. **NVIDIA Parakeet/Canary real RTF numbers on comparable hardware.** Not found with a confident citation in the time available — needs a further targeted search or a direct benchmark run.
7. **Fireworks AI pricing for a comparable model class.** Not retrieved in this pass.
8. **Whether pyannote diarisation output is actually consumed by T6's prompt today.** Needs a direct code read of the T6 call path for speaker-label wiring (not attempted in this audit, which focused on latency/architecture).

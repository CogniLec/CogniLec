# Multi-GPU Setup — Running S02/S36/S18/S25 Across Multiple Physical Cards

## What this actually is (read this first)

This project's GPU-heavy pieces — ASR (faster-whisper), embedding
(sentence-transformers), vLLM (Tier-1 LLM serving), and diarisation
(pyannote, an isolated container) — each load a **small model** that fits
comfortably on one 4GB card. Splitting one of those models across multiple
GPUs (tensor parallelism) isn't worth it here: the inter-GPU communication
overhead would likely cost more than it saves at this model size.

What this setup actually buys you: **running independent pipeline stages
on separate physical GPUs simultaneously**, so ASR, diarisation, and
embedding for different sessions can all be in flight at once instead of
serialized on a single card. That's a real throughput win for a batch of
lectures, which is this project's actual workload.

**Honesty note** (see `docs/gaps.md` gap #21): the config below was built
and verified correct on a single-GPU host — device index 0 (the default)
is confirmed working end to end. Genuine multi-GPU concurrent execution
and any resulting speedup has **not** been measured anywhere, because no
machine with more than one GPU has been available to test on. Follow this
guide, but treat the "it actually runs faster with 3 GPUs" claim as
unverified until you've run it yourself and checked.

## Step 1 — Confirm you actually have multiple GPUs

```bash
nvidia-smi -L
```

You should see one line per physical card, e.g.:

```
GPU 0: NVIDIA T1000 (UUID: GPU-xxxxxxxx-...)
GPU 1: NVIDIA T1000 (UUID: GPU-yyyyyyyy-...)
GPU 2: NVIDIA T1000 (UUID: GPU-zzzzzzzz-...)
```

The number before the colon (`0`, `1`, `2`, ...) is the **device index**
everything below refers to. If this only shows one GPU, none of the rest
of this doc will do anything for you — the app will just run on device 0
regardless of what you set.

## Step 2 — Decide which stage goes on which card

There are four independent settings, one per GPU-using stage:

| Setting                 | Controls                                   | Where it's used                                    |
|--------------------------|---------------------------------------------|-----------------------------------------------------|
| `ASR_CUDA_DEVICE`         | faster-whisper transcription                | `src/workers/asr_worker.py` (in-process)             |
| `EMBEDDING_CUDA_DEVICE`   | sentence-transformers embedding             | `src/api/routes/search.py`'s `EmbeddingClient` call (in-process) |
| `VLLM_GPU_DEVICE`         | the isolated vLLM container (S36 Tier-1 LLM) | `docker-compose.yml`'s `vllm` service (own container) |
| `DIARISATION_GPU_DEVICE`  | the isolated diarisation container (S20)     | `docker-compose.yml`'s `diarisation` service (own container) |

With 3 physical GPUs, a reasonable split is:

- **GPU 0**: ASR + embedding (both lightweight, in-process, can share a card)
- **GPU 1**: vLLM (Tier-1 LLM serving — runs continuously as its own container)
- **GPU 2**: diarisation (runs per-session, its own container)

There's nothing special about this split — it's just one way to spread
four consumers across three cards without doubling any of them up
unnecessarily. Adjust to your actual hardware and workload.

## Step 3 — Set the environment variables

Edit your `.env` (copy from `.env.example` if you don't have one yet) and
set the four device variables from Step 2:

```bash
# .env
ASR_CUDA_DEVICE=0
EMBEDDING_CUDA_DEVICE=0
VLLM_GPU_DEVICE=1
DIARISATION_GPU_DEVICE=2
```

These are all plain integers matching the device indices from
`nvidia-smi -L` in Step 1. Leaving any of them unset defaults to `0`
(safe on a single-GPU host — that's the config this repo has actually
been tested against).

## Step 4 — Start the containerized services (vLLM, diarisation)

These pick up their GPU assignment from `docker-compose.yml`'s
`device_ids: ["${VLLM_GPU_DEVICE:-0}"]` / `["${DIARISATION_GPU_DEVICE:-0}"]`
— Docker Compose reads the env vars from your `.env` automatically.

```bash
docker compose --profile llm up -d vllm
docker compose --profile diarisation up -d diarisation
```

Verify each container actually landed on the GPU you asked for:

```bash
docker exec lis-vllm nvidia-smi -L
docker exec lis-diarisation nvidia-smi -L
```

Each should show **only** the one card you assigned it (Docker's
`device_ids` reservation restricts what the container can see) — if you
see all your GPUs listed inside the container, the reservation didn't
take effect; double check `VLLM_GPU_DEVICE`/`DIARISATION_GPU_DEVICE` are
actually set in the environment `docker compose` is reading from (run
`docker compose config` and check the rendered `device_ids` values).

## Step 5 — Start the in-process services (ASR, embedding)

These read `ASR_CUDA_DEVICE`/`EMBEDDING_CUDA_DEVICE` from
`src/core/config.py`'s `Settings` at process startup — no Docker
involved, just make sure your shell/`.env` has the values set before
launching:

```bash
source .venv/bin/activate
python -m src.workers.asr_worker
```

To confirm the ASR worker actually picked the right device, check its
startup log line — `src/services/asr/service.py` logs
`device_index=<N>` when it loads the model:

```
loading faster-whisper model ... device_index=0
```

The embedding client (`src/ml/embedding/client.py`) is instantiated
per-request inside `src/api/routes/search.py`, not at process startup —
it'll use whatever `EMBEDDING_CUDA_DEVICE` is set to at request time.

## Step 6 — Watch all cards while it runs

```bash
watch -n1 nvidia-smi
```

With the pipeline actually running (a real session being transcribed +
diarised + embedded concurrently), you should see utilization on more
than one GPU line at once. If everything's still landing on one card,
recheck Step 3's env vars are actually being picked up by whichever
process you're looking at (`echo $ASR_CUDA_DEVICE` in the shell that
launched the worker, `docker compose config | grep device_ids` for the
containers).

## Troubleshooting

- **"CUDA error: invalid device ordinal"** — you set a device index that
  doesn't exist (e.g. `ASR_CUDA_DEVICE=2` on a 2-GPU host, where valid
  indices are `0` and `1`). Recheck `nvidia-smi -L`'s output from Step 1.
- **Container shows all GPUs, not just the one assigned** — the
  `device_ids` reservation in `docker-compose.yml` isn't taking effect.
  Run `docker compose --profile llm --profile diarisation config` (the
  `--profile` flags are required — these two services are profile-gated
  and `docker compose config` silently omits them without it) and confirm
  the rendered value under `vllm`/`diarisation`'s
  `deploy.resources.reservations.devices` actually shows your intended
  device id, not `"0"` by default (meaning your env var wasn't picked up).
- **Everything still serializes on one card despite different indices set**
  — confirm you're not accidentally also setting the global
  `CUDA_VISIBLE_DEVICES` env var to a single value that masks the
  per-stage settings; that variable is separate from the four in this doc
  and restricts what CUDA even considers "device 0" from a process's point
  of view. Leave `CUDA_VISIBLE_DEVICES` unset (or set to all your GPUs,
  e.g. `0,1,2`) and let the per-stage `_CUDA_DEVICE`/`_GPU_DEVICE`
  variables do the actual pinning.

## What to report back once you've tried this for real

Since this has only been verified on a single-GPU host, if you run this
on your actual 3-GPU machine, it'd be worth checking and noting:

1. Did each service actually land on the GPU you assigned it (Step 4/6)?
2. Did processing multiple sessions concurrently actually show
   multi-GPU utilization (Step 6), not just one card doing all the work?
3. Any wall-clock speedup on a batch of sessions vs. running them one at
   a time on a single GPU?

That closes the "unverified" note at the top of this doc and in
`docs/gaps.md` gap #21.

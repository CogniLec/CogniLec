# Multi-Machine GPU Setup — Running Across 3 Separate Hosts

## What this actually is (read this first)

**This is not about multiple GPU cards in one machine.** You have 3
separate physical machines, each with its own single GPU. That's a
genuinely different setup from pinning devices on one host: instead of
`CUDA_VISIBLE_DEVICES`/device indices, the real knob is **which machine's
IP address each service's URL points at**.

The GPU-heavy pieces in this project are:

| Service     | What it does                          | Deployment shape today                          |
|-------------|----------------------------------------|--------------------------------------------------|
| ASR         | faster-whisper transcription           | In-process worker (`src/workers/asr_worker.py`) |
| Embedding   | sentence embeddings for search/clustering | Real HTTP service (TEI) with local CPU/GPU fallback |
| vLLM        | Tier-1 local LLM serving               | Isolated Docker container                        |
| Diarisation | speaker separation (pyannote)          | Isolated Docker container                        |

The two containerized services (vLLM, diarisation) were already built to
run as separate network services — they just needed a real second/third
machine to actually prove that. The embedding service (TEI) previously had
no `docker-compose.yml` entry and no config wiring at all — it's been
added as part of this update (see the "What changed" section at the
bottom) so it can genuinely be its own machine too, not just an unused
class default.

ASR is the one exception: it's an in-process Python worker, not a
network service. To run it on a different machine, you run the worker
process itself on that machine — it doesn't need a URL, but it does need
network access to Postgres, MinIO, and Valkey (all on whichever machine
hosts the core stack).

**Honesty note**: this has only been verified on a single machine (one
GPU, gap #15/#17/#20/#21). The container/service wiring is real and
correct by inspection, but genuine cross-machine execution — reaching a
service across your LAN, not `localhost` — has not been tested end to
end. Follow this guide, verify each step's checks, and treat "it actually
works across 3 machines" as unconfirmed until you've done that yourself.

## Step 0 — Decide which machine runs what

With 3 machines and 4 GPU-consumers, one machine will host two things.
A reasonable split:

- **Machine A** (core stack): Postgres, MinIO, Valkey, the API, the ASR
  worker. This is "home base" — everything else needs to reach it.
- **Machine B**: vLLM (Tier-1 LLM serving) — runs continuously.
- **Machine C**: TEI (embedding) + diarisation — TEI runs continuously,
  diarisation only when a session actually needs it, so sharing a machine
  is fine.

There's nothing special about this split; swap ASR onto Machine B or C if
that fits your hardware better. The point is: figure out each machine's
LAN IP address first (`ip addr show` or `hostname -I` on each).

## Step 1 — Confirm each machine actually has its GPU working

On **each** of the 3 machines:

```bash
nvidia-smi -L
```

Each should show exactly one GPU. If any machine shows none, stop and fix
that machine's driver/CUDA setup before continuing — none of the network
wiring below will help if the GPU itself isn't visible on that host.

## Step 2 — Machine A: core stack + ASR worker

On Machine A, bring up the base stack as usual:

```bash
docker compose up -d
```

The ASR worker runs in-process on whichever machine you launch it from —
launch it here:

```bash
source .venv/bin/activate
python -m src.workers.asr_worker
```

Its `.env` needs to point at wherever Postgres/MinIO/Valkey actually are
— if they're all on Machine A too (the setup above), the defaults
(`localhost`) are fine only if you're running the worker on Machine A
itself. If you later move the ASR worker to a different machine, update
`DATABASE_URL`, `MINIO_ENDPOINT`, and `VALKEY_URL` in that machine's
`.env` to Machine A's real LAN IP instead of `localhost`.

`ASR_CUDA_DEVICE` stays `0` here — it selects a device index on *this*
machine, and each machine only has one GPU (device `0`).

## Step 3 — Machine B: vLLM

On Machine B, you only need Docker and this repo checked out (the whole
stack doesn't need to run here, just the one service):

```bash
# .env on Machine B
VLLM_GPU_DEVICE=0

docker compose --profile llm up -d vllm
```

Verify it's actually listening and reachable from Machine A:

```bash
# on Machine B itself
curl http://localhost:8000/health

# on Machine A, using Machine B's real LAN IP
curl http://<machine-b-ip>:8000/health
```

If the second command fails but the first works, it's a firewall/network
issue on Machine B (Docker's `ports:` mapping binds to `0.0.0.0` by
default, so this is almost always a host firewall blocking the port, not
a Docker config problem) — check `ufw status` / `iptables` on Machine B.

**Point the rest of the system at Machine B.** `config/litellm.yaml`'s
`api_base` fields resolve via LiteLLM's `os.environ/VAR_NAME`
substitution (the same mechanism it already uses for `api_key:
os.environ/OPENAI_API_KEY`), so this no longer means hand-editing that
YAML file per deployment — just set the env var on whichever machine
runs the `litellm` container:

```bash
# .env, on the machine running the litellm container (Machine A here)
VLLM_API_BASE=http://<machine-b-ip>:8000/v1

docker compose --profile llm up -d litellm   # or: docker compose restart litellm
```

`LLAMACPP_API_BASE` works the same way if you're also running the
CPU-tier `llamacpp` service on a different machine.

## Step 4 — Machine C: TEI (embedding) + diarisation

```bash
# .env on Machine C
DIARISATION_GPU_DEVICE=0
HF_TOKEN=<your real token, needed for pyannote — see gap #17>

docker compose --profile embedding --profile diarisation up -d tei diarisation
```

Verify both:

```bash
# on Machine C
curl http://localhost:8090/health   # TEI
curl http://localhost:8100/health   # diarisation

# on Machine A, using Machine C's real LAN IP
curl http://<machine-c-ip>:8090/health
curl http://<machine-c-ip>:8100/health
```

**Point Machine A at Machine C.** In Machine A's `.env`:

```bash
TEI_BASE_URL=http://<machine-c-ip>:8090
DIARISATION_SERVICE_URL=http://<machine-c-ip>:8100
```

If TEI is unreachable for any reason, `EmbeddingClient` (`src/ml/embedding/client.py`)
silently falls back to local sentence-transformers on whichever machine
made the call — search keeps working, just without the dedicated GPU
service. That fallback is real and already tested; the network path to a
remote TEI is the part that's new and unverified here.

## Step 5 — Restart Machine A's app with the new URLs

```bash
# on Machine A
docker compose restart api   # or however you're running the API process
```

Then confirm the whole chain works: hit a search endpoint through the
real API and check its response — if TEI is reachable, the query
embedding step used it; if not, it silently used the local fallback (you
can tell by checking Machine C's TEI container logs for an incoming
request at the same time you fire the search).

## Troubleshooting

- **"Connection refused" from Machine A to B or C** — almost always a
  firewall on the target machine blocking the port, not a code issue.
  Confirm with `curl` from the target machine itself first (Step 3/4
  above), then from Machine A.
- **vLLM/TEI/diarisation container won't see its GPU** — `nvidia-smi -L`
  inside the container (`docker exec <container> nvidia-smi -L`) should
  show exactly the one GPU on that machine. If it shows none, the
  NVIDIA Container Toolkit likely isn't installed/configured on that
  specific machine — this is a per-machine setup step, not something the
  `docker-compose.yml` device reservation can fix by itself.
- **Search results look identical whether TEI is up or down** — that's
  the fallback working as designed, not a bug; check TEI's own logs to
  confirm whether it's actually receiving requests.
- **LiteLLM can't reach vLLM after changing `VLLM_API_BASE`** — the
  LiteLLM proxy container needs restarting to pick up the new env var:
  `docker compose restart litellm`.

## What to report back once you've tried this for real

1. Did `curl` from Machine A actually reach Machine B's vLLM and Machine
   C's TEI/diarisation over the real network (not just `localhost` on
   each machine individually)?
2. Did a real search request's query embedding actually route through
   Machine C's TEI (checkable via TEI's container logs), or silently fall
   back to local?
3. Did the LiteLLM tier-1 route actually hit Machine B's vLLM for a real
   completion?

That's what would turn this from "wired correctly by inspection" into
"verified working across 3 real machines."

## What changed in this update

Previously this doc assumed 3 GPU cards in one machine and described
`CUDA_VISIBLE_DEVICES`/device-index pinning — the wrong setup for 3
separate machines. Along the way, a real gap was found and fixed:
**TEI (S25's embedding service) had no `docker-compose.yml` entry and no
config setting at all** — `EmbeddingClient`'s `tei_base_url` default
(`http://tei:80`) pointed at a hostname that resolved nowhere, so every
embedding call was silently using the local fallback, always, regardless
of intent. Added:

- `TEI_BASE_URL` setting in `src/core/config.py`
- A real `tei` service in `docker-compose.yml` (matching the exact image/
  command from `docs/specs/block-4-embedding-topic-intelligence.md`
  §6.1), gated behind a new `embedding` compose profile
- `src/api/routes/search.py` now actually passes `settings.TEI_BASE_URL`
  into `EmbeddingClient` instead of leaving the unreachable class default
  in place
- `TEI_BASE_URL`/`TEI_IMAGE_TAG`/`TEI_PORT` added to `.env.example`

A second gap was also closed: **`config/litellm.yaml` hardcoded
`api_base: http://vllm:8000/v1` / `http://llamacpp:8080/v1`**, requiring a
manual per-deployment edit of that file to run vLLM on a separate
machine (exactly what this doc used to instruct in Step 3). Fixed by
switching both `api_base` fields to LiteLLM's own `os.environ/VAR_NAME`
substitution (already used for `api_key` in the same file):

- `config/litellm.yaml`: `api_base: os.environ/VLLM_API_BASE` and
  `os.environ/LLAMACPP_API_BASE`
- `VLLM_API_BASE`/`LLAMACPP_API_BASE` added to `.env.example`, and passed
  through to the `litellm` container's `environment:` in
  `docker-compose.yml`
- Step 3 above now sets an env var and restarts the container instead of
  hand-editing YAML

Full test suite re-run after these changes: 711 passed, 82 skipped, no
regressions (see `docs/gaps.md`).

# Setup Guide: Clone to Running, Then Distributing Across 3 GPU Machines

This doc has two parts:

- **Part 1** — the base setup: clone the repo, install dependencies, bring
  up the stack, run migrations, start the API and worker, start the
  frontend. Everything here runs on one machine and is what you need
  regardless of how many GPUs you have.
- **Part 2** — once the base setup works on one machine, this covers
  spreading the 4 GPU-heavy pieces (ASR, embedding, vLLM, diarisation)
  across **3 separate physical machines**, each with its own single GPU —
  not 3 GPU cards in one host. That's a genuinely different setup from
  pinning devices on one host: instead of `CUDA_VISIBLE_DEVICES`/device
  indices, the real knob is **which machine's IP address each service's
  URL points at**.

If you only have one machine (with 0 or 1 GPU), stop after Part 1 — that's
a complete, working setup on its own.

---

## Part 1 — Base setup (single machine)

### Step 1 — Prerequisites

Install on the machine that will run the core stack:

- **Docker + Docker Compose v2** (`docker compose version` should work)
- **[uv](https://docs.astral.sh/uv/)** (Python package/venv manager) —
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Node.js 20+** (for the frontend) — via [nvm](https://github.com/nvm-sh/nvm)
  if your system Node is old: `nvm install 20 && nvm use 20`
- **Git**
- If you plan to run any GPU-backed stage on this machine: an NVIDIA GPU
  with a working driver, and the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  so Docker containers can see it. Confirm with `nvidia-smi -L` (bare
  metal) — this must show your GPU before any of the containerized GPU
  services below will work.

### Step 2 — Clone the repo

```bash
git clone <this-repo-url> lis
cd lis
```

### Step 3 — Python environment

```bash
uv sync --extra dev
```

Always include `--extra dev` — a bare `uv sync` strips pytest/mypy/ruff
from the venv, which then silently breaks pre-commit hooks and test runs.
This creates `.venv/` with everything the API, workers, and test suite
need.

### Step 4 — Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and set real values for at least:

- `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`/`MINIO_SECRET_KEY`,
  `VALKEY_PASSWORD`, `PGADMIN_PASSWORD`, `SECRET_KEY` (the placeholder
  `changeme_*` values are not safe to run with, even locally)
- `HF_TOKEN` — a real Hugging Face token with access to
  `pyannote/speaker-diarization-3.1` (accept that model's terms on HF
  first); needed for real diarisation, see `docs/gaps.md` gap #17
- Leave the GPU/service-address block (`ASR_CUDA_DEVICE`,
  `TEI_BASE_URL`, `VLLM_API_BASE`, `DIARISATION_SERVICE_URL`, etc.) at
  its defaults for now — Part 2 covers changing those for a
  multi-machine deployment.

### Step 5 — Bring up the core stack

```bash
docker compose up -d
```

This starts everything with no `profiles:` gate — Postgres (`pg-main`,
`pg-syllabus`), `pgbouncer`, `valkey`, `minio` (+ `minio-init` to create
buckets), `pgadmin`, `traefik`, `dozzle`, `portainer`, `label-studio`,
`mlflow`. GPU-heavy services (`vllm`, `diarisation`, `tei`) and
`litellm`/`langfuse` are gated behind profiles and stay down until you
ask for them explicitly — see Step 7 and Part 2.

Check everything came up healthy:

```bash
docker compose ps
```

### Step 6 — Run database migrations

```bash
source .venv/bin/activate
alembic upgrade head
```

This creates the full schema on `pg-main` (users, subjects, sessions,
chunks, corrections, etc.) and, via the S11 `postgres_fdw` migration,
wires the foreign-table link to `pg-syllabus`.

### Step 7 — Start the API

```bash
source .venv/bin/activate
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

`src/api/main.py` assembles all route modules into one FastAPI app.
Confirm it's up:

```bash
curl http://localhost:8000/docs   # interactive OpenAPI docs
```

### Step 8 — Start the ASR worker

In a second terminal:

```bash
source .venv/bin/activate
python -m src.workers.asr_worker
```

This is an in-process Python worker (not a container) that pulls audio
chunks off the queue, transcribes them with faster-whisper, and writes
results back to Postgres/MinIO. It needs GPU access on whichever machine
it runs on (`ASR_CUDA_DEVICE`, default `0`).

### Step 9 — Start the frontend

```bash
cd src/client
npm install   # first time only
npm run dev
```

Vite serves the dev build, by default at `http://localhost:5173`. It
talks to the API at the URL configured in `src/client`'s own env/config
— point it at `http://localhost:8000` (or wherever you're running the
API from Step 7) if it isn't already.

### Step 10 — Smoke-test the whole chain

1. Open the frontend URL in a browser.
2. Register a user, log in.
3. Create a subject.
4. Start a recording session (needs a real microphone on whatever
   machine's browser you're testing from) and confirm chunks are being
   captured and transcribed.

At this point you have a fully working single-machine deployment. The
GPU-heavy services beyond ASR (embedding, vLLM, diarisation) will either
be unavailable (diarisation/vLLM, since their containers aren't up yet —
start them with `docker compose --profile diarisation up -d diarisation`
and `docker compose --profile llm up -d vllm` if this one machine has
enough GPU headroom) or silently falling back to a local/CPU path
(embedding — see `src/ml/embedding/client.py`). Continue to Part 2 only
if you actually have 3 separate machines and want to spread these across
real network hosts instead.

---

## Part 2 — Distributing GPU work across 3 machines

**This is not about multiple GPU cards in one machine.** If you have 3
separate physical machines, each with its own single GPU, this section
is for you. The knob is **which machine's IP address each service's URL
points at**, not `CUDA_VISIBLE_DEVICES`/device indices.

The GPU-heavy pieces in this project are:

| Service     | What it does                          | Deployment shape today                          |
|-------------|----------------------------------------|--------------------------------------------------|
| ASR         | faster-whisper transcription           | In-process worker (`src/workers/asr_worker.py`) |
| Embedding   | sentence embeddings for search/clustering | Real HTTP service (TEI) with local CPU/GPU fallback |
| vLLM        | Tier-1 local LLM serving               | Isolated Docker container                        |
| Diarisation | speaker separation (pyannote)          | Isolated Docker container                        |

The two containerized services (vLLM, diarisation) were already built to
run as separate network services. The embedding service (TEI) and
LiteLLM's `api_base` fields previously had no way to point at a real
remote machine (no compose entry / hardcoded internal hostnames) — both
have since been fixed to be genuinely cross-machine-capable (see "What
changed" at the bottom).

ASR is the one exception: it's an in-process Python worker, not a
network service. To run it on a different machine, you run the worker
process itself on that machine (Step 8 above) — it doesn't need a URL,
but it does need network access to Postgres, MinIO, and Valkey (all on
whichever machine hosts the core stack from Part 1).

**Honesty note**: this has only been verified on a single machine (one
GPU, gap #15/#17/#20/#21). The container/service wiring is real and
correct by inspection, but genuine cross-machine execution — reaching a
service across your LAN, not `localhost` — has not been tested end to
end. Follow this guide, verify each step's checks, and treat "it actually
works across 3 machines" as unconfirmed until you've done that yourself.

### Step 0 — Decide which machine runs what

With 3 machines and 4 GPU-consumers, one machine will host two things.
A reasonable split, assuming Machine A is the one you set up in Part 1:

- **Machine A** (core stack): Postgres, MinIO, Valkey, the API, the ASR
  worker. This is "home base" — everything else needs to reach it.
- **Machine B**: vLLM (Tier-1 LLM serving) — runs continuously.
- **Machine C**: TEI (embedding) + diarisation — TEI runs continuously,
  diarisation only when a session actually needs it, so sharing a machine
  is fine.

There's nothing special about this split; swap ASR onto Machine B or C if
that fits your hardware better. The point is: figure out each machine's
LAN IP address first (`ip addr show` or `hostname -I` on each).

### Step 1 — Confirm each machine actually has its GPU working

On **each** of the 3 machines:

```bash
nvidia-smi -L
```

Each should show exactly one GPU. If any machine shows none, stop and fix
that machine's driver/CUDA setup before continuing — none of the network
wiring below will help if the GPU itself isn't visible on that host.

### Step 2 — Machine A: core stack + ASR worker

This is Part 1, Steps 2–8, done on Machine A specifically. If you've
already completed Part 1 there, nothing new to do here — just confirm:

```bash
docker compose ps                 # core stack up
curl http://localhost:8000/docs   # API up
```

`ASR_CUDA_DEVICE` stays `0` — it selects a device index on *this*
machine, and each machine only has one GPU (device `0`).

If you're moving the ASR worker to Machine B or C instead of running it
on Machine A, update `DATABASE_URL`, `MINIO_ENDPOINT`, and `VALKEY_URL`
in that machine's `.env` to Machine A's real LAN IP instead of
`localhost` before launching `python -m src.workers.asr_worker` there.

### Step 3 — Machine B: vLLM

On Machine B, you only need Docker and this repo checked out (clone it
here too — the whole stack doesn't need to run, just the one service):

```bash
git clone <this-repo-url> lis
cd lis
cp .env.example .env
```

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

### Step 4 — Machine C: TEI (embedding) + diarisation

```bash
git clone <this-repo-url> lis
cd lis
cp .env.example .env
```

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

### Step 5 — Restart Machine A's app with the new URLs

```bash
# on Machine A
docker compose restart api   # or however you're running the API process
```

Then confirm the whole chain works: hit a search endpoint through the
real API and check its response — if TEI is reachable, the query
embedding step used it; if not, it silently used the local fallback (you
can tell by checking Machine C's TEI container logs for an incoming
request at the same time you fire the search).

### Troubleshooting

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
- **`uv sync` strips pytest/mypy/ruff** — you ran it without
  `--extra dev`. Re-run `uv sync --extra dev`.
- **`/auth/register` or other API calls fail with a DB error right after
  a fresh clone** — you likely skipped Step 6 (`alembic upgrade head`);
  the schema doesn't exist yet on a brand-new Postgres volume.

### What to report back once you've tried this for real

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

This doc originally covered only the GPU-distribution piece and assumed
3 GPU cards in one machine (`CUDA_VISIBLE_DEVICES`/device-index pinning)
— the wrong setup for 3 separate machines. It was rewritten around real
network addresses instead of device indices, and then expanded with a
full Part 1 (clone through running frontend) so the doc is a complete
start-to-finish guide rather than assuming the reader already has a
working single-machine deployment.

Two real code gaps were also found and fixed while doing this (not just
documentation):

1. **TEI (S25's embedding service) had no `docker-compose.yml` entry and
   no config setting at all** — `EmbeddingClient`'s `tei_base_url` default
   (`http://tei:80`) pointed at a hostname that resolved nowhere, so every
   embedding call was silently using the local fallback, always,
   regardless of intent. Added:
   - `TEI_BASE_URL` setting in `src/core/config.py`
   - A real `tei` service in `docker-compose.yml` (matching the exact
     image/command from
     `docs/specs/block-4-embedding-topic-intelligence.md` §6.1), gated
     behind a new `embedding` compose profile
   - `src/api/routes/search.py` now actually passes `settings.TEI_BASE_URL`
     into `EmbeddingClient` instead of leaving the unreachable class
     default in place
   - `TEI_BASE_URL`/`TEI_IMAGE_TAG`/`TEI_PORT` added to `.env.example`

2. **`config/litellm.yaml` hardcoded `api_base: http://vllm:8000/v1` /
   `http://llamacpp:8080/v1`**, requiring a manual per-deployment edit of
   that file to run vLLM on a separate machine. Fixed by switching both
   `api_base` fields to LiteLLM's own `os.environ/VAR_NAME` substitution
   (already used for `api_key` in the same file):
   - `config/litellm.yaml`: `api_base: os.environ/VLLM_API_BASE` and
     `os.environ/LLAMACPP_API_BASE`
   - `VLLM_API_BASE`/`LLAMACPP_API_BASE` added to `.env.example`, and
     passed through to the `litellm` container's `environment:` in
     `docker-compose.yml`
   - Step 3 above now sets an env var and restarts the container instead
     of hand-editing YAML

Full test suite re-run after these changes: 711 passed, 82 skipped, no
regressions (see `docs/gaps.md`).

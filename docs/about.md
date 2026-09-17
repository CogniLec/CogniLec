# About this project (session bootstrap)

Read this first in a new session before diving into code or `docs/gaps.md`.
This gives you enough context to be useful immediately without re-deriving
the whole system from scratch.

## What this is

**Notely** (repo: `CogniLec/CogniLec`, internal name "LIS" / "Lecture
Intelligence System" in code comments) — a lecture-capture app: record a
live lecture on a phone/laptop, and it automatically transcribes, takes
structured notes, and generates spaced-repetition flashcards, all running
on self-hosted open-weight models (no OpenAI/Anthropic API calls in the
default path — see ADR-018).

- **Frontend**: `src/client/` — a React PWA (Vite + vite-plugin-pwa),
  deployed to GitHub Pages at https://cognilec.github.io/CogniLec/, and
  also runnable locally via Docker (`lis-client`, localhost:8081).
- **Backend**: FastAPI (`src/api/`) + a set of Valkey-stream-driven workers
  (`src/workers/`) + Prefect flows for the post-transcription pipeline
  (`src/services/orchestration/session_pipeline.py`).
- **Public access**: the frontend needs a public URL for the backend API,
  since the backend runs on a local machine with no public IP. Currently
  **Tailscale Funnel** (`https://ashok-3.tail7148e0.ts.net`, permanent,
  survives reboots) — see gap #33d in `docs/gaps.md` for the history (it
  was Cloudflare quick tunnel before, which got revoked and broke the
  public site; don't reintroduce that without reading why it was replaced).

## Hardware / deployment topology

Three physical machines (see `docs/multi-gpu-setup.md` for full setup
steps), each with a single 4GB-VRAM GPU (ADR-015 — this exact constraint
drives almost every model-selection and quantization decision in the repo):

- **Machine A** (this host, wherever you're running Claude Code): Postgres,
  MinIO, Valkey, the API, the ASR worker, and (as of 2026-09-17) a second
  vLLM instance for load-balanced LLM throughput.
- **Machine B**: primary vLLM instance (Tier-1 LLM, `Qwen/Qwen2.5-3B-Instruct-AWQ`).
- **Machine C**: TEI (embedding service) + diarisation (on-demand).

## The pipeline, one line each (see `docs/working.md` for the full version)

Record → chunk-upload → preprocess → ASR transcribe → embed → segment →
cluster → **label topics** → filter relevance (A1) → synthesize notes (A2)
→ persist → auto-generate flashcards. All of this after the final chunk
(`is_final=true`) is auto-triggered, no manual step, by
`src/workers/asr_worker.py` calling
`src/services/orchestration/auto_study_materials.py`.

## Things that will bite you if you don't know them

1. **Every subject needs a database partition** (`utterances`/`segments`/
   etc. are all partitioned by `subject_id`, pg_partman-style). New
   subjects get one automatically now (fixed gap #33), but **any subject
   created before 2026-09-17 does not have one** and will silently fail to
   persist any real transcript data. If a real user's recording produces
   zero utterances despite a healthy pipeline, check this first:
   `\dt utterances_<subject_id_prefix>*` in psql. Fix with
   `PartitionProvisioner()._create_partitions(db, subject_id, hex, str)`
   (see gap history for the exact one-liner).
2. **Short recordings (a few minutes) often produce 0 flashcards even when
   everything works correctly.** Clustering (T3) needs enough segments to
   form a real topic; with too little material it produces 0 topics, which
   makes downstream relevance filtering degrade to judging against a
   meaningless "unlabeled topic" placeholder and reject everything. This is
   not a bug — recommend 5+ minutes of real content for a meaningful demo.
3. **This hardware is genuinely slow.** A 5-minute lecture takes roughly
   8-20 minutes to fully process (varies with LLM backend count/load).
   This is inherent to running a 3B model on a 4GB card with constrained
   decoding, not a wiring problem — don't assume "it's stuck," check
   Prefect task states before concluding something's broken.
4. **The small LLM occasionally produces malformed/invalid output**
   (missing fields, duplicate ordinals, non-JSON). Guided/constrained
   decoding (`guided_json`, wired into A1 and A2 as of 2026-09-17)
   drastically reduced this but didn't eliminate it — Prefect's built-in
   retries (2 per task) handle most of it. A single failed run on real
   content is not necessarily a regression; check if it's this known class
   of flake before chasing it as a new bug.
5. **The PWA aggressively precaches the JS bundle**, including a
   build-time-baked backend URL. Users on a stale bundle after any backend
   URL change get "failed to fetch" that looks like a login bug but isn't
   (fixed 2026-09-17 with skipWaiting/clientsClaim + reload-on-update, but
   any browser that had the app open *before* that fix shipped needs one
   manual full cache-clear to get past the old, pre-fix service worker).

## Where to go next

- `docs/gaps.md` — the running log of every real bug found, root-caused,
  and fixed (or explicitly left open) across this project's whole history.
  Read the most recent few entries (search for the highest `##` number) to
  know what was worked on most recently before you arrived.
- `docs/working.md` — what each pipeline stage actually does.
- `docs/multi-gpu-setup.md` — exact machine setup steps.
- `docs/adrs/` — the *why* behind major architecture decisions (numbered,
  short, worth skimming the titles at minimum).
- This session's plan file (if one exists) may have a live, in-progress
  task list — check for a recent one before assuming there's nothing
  queued.

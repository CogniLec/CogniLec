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

**Machine A's GPU is fully committed — there is no spare capacity here.**
Confirmed live (2026-09-20/21, `docs/gaps.md` #34): the local vLLM instance
alone uses ~2.8GB of the T1000's 4GB, plus ~400-600MB from this machine's
own desktop session (Xorg/gnome-shell/browser, and it's a gaming laptop —
GPU also gets claimed during play). ASR was fixed to support GPU
transcription (nvidia-cublas-cu12/nvidia-cudnn-cu12 now real dependencies,
`docker-compose.yml`'s default is `ASR_DEVICE=cuda`), but turning it on
here immediately OOMs. This host currently runs ASR on **CPU** via a
local, uncommitted `.env` override (`ASR_DEVICE=cpu`) — don't "fix" this
by flipping it back to cuda without first freeing GPU headroom (stop the
local vLLM, or get a genuinely separate GPU for ASR).

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
   `docs/audit/pipeline-overhaul.md` (2026-09-20) has the full latency
   breakdown, real measured utterance-density numbers, and a prioritized
   fix list — read it before proposing "make it faster" changes so you
   don't re-derive what's already been measured.
4. **T6 (note synthesis) used to have a hard correctness ceiling, now
   fixed.** It sent the entire filtered transcript in ONE LLM call; past
   ~13 minutes of real lecture content (measured, not guessed — see the
   audit), that call exceeded the model's 2048-token context window and
   silently produced **zero notes**, not just a slow result. Fixed
   2026-09-20/21 (gap #34): `NoteSynthesisAgent.synthesize()` now chunks
   utterances into groups of 25. If you're touching `note_synthesis.py`,
   know this history before "simplifying" it back to one call.
5. **The small LLM occasionally produces malformed/invalid output**
   (missing fields, duplicate ordinals, non-JSON). Guided/constrained
   decoding (`guided_json`, wired into A1 and A2 as of 2026-09-17)
   drastically reduced this but didn't eliminate it — Prefect's built-in
   retries (2 per task) handle most of it. A single failed run on real
   content is not necessarily a regression; check if it's this known class
   of flake before chasing it as a new bug.
6. **The PWA aggressively precaches the JS bundle**, including a
   build-time-baked backend URL. Users on a stale bundle after any backend
   URL change get "failed to fetch" that looks like a login bug but isn't
   (fixed 2026-09-17 with skipWaiting/clientsClaim + reload-on-update, but
   any browser that had the app open *before* that fix shipped needs one
   manual full cache-clear to get past the old, pre-fix service worker).

## Current task in progress: live-demo strategy for a 60+ minute recording

The user needs a **live demo**: record 60+ minutes of audio live, have it
**transcribe live** (real-time, keeping pace with the speaker), and have
**notes/flashcards appear soon after recording stops** (not 30-70+
minutes later, which is what the current pipeline would actually take for
a real 60-minute lecture per the audit's measured numbers).

**Where this stands, not yet decided/built:**

- **Live transcription** genuinely needs GPU-speed ASR for an hour of
  continuous speech — CPU can't keep up in real time at that length. But
  see the GPU-contention note above: this host's GPU is already ~85%
  claimed by its own vLLM instance, so turning ASR back to `cuda` here
  OOMs. Real options discussed, none yet chosen/implemented:
  1. Temporarily stop the local vLLM instance for the demo window, free
     the GPU for ASR (uses the already-built P1 fix, zero new
     infrastructure, but loses the local vLLM round-robin backend for
     T5/T6 during the demo).
  2. Rent a small cloud GPU for the demo window (Vast.ai RTX 3060-class,
     ~$0.03-0.05/hr, ~$22-36/mo if left running 24/7 — but a demo only
     needs it for the demo's duration).
  3. Swap the ASR *source* entirely for a cloud/free transcription
     service. Confirmed via reading the actual code
     (`segmentation.py`, `relevance_filter.py`, `note_synthesis.py`):
     **T1-T7 downstream of ASR only ever consume `seq` (ordinal
     position) + text — no code path reads word/utterance timestamps.**
     So any service that returns transcript text *in order* (even with
     no timestamps at all) is a legitimate, low-effort swap for
     `FasterWhisperASRService` — this is a much smaller change than it
     first sounds, isolated to the ASR stage only. **IMPLEMENTED
     2026-09-21** (untested live -- no API key yet):
     `src/services/asr/external.py` (`ExternalASRService`, OpenAI-
     compatible `/audio/transcriptions`, works with Groq/OpenAI/Together/
     self-hosted faster-whisper-server). Enable via `.env`:
     `ASR_BACKEND=external`, `ASR_EXTERNAL_API_KEY=...`, optionally
     `ASR_EXTERNAL_BASE_URL` / `ASR_EXTERNAL_MODEL` (defaults: Groq,
     `whisper-large-v3-turbo`), then recreate `asr-worker`. Default stays
     `local`. Unit-tested with a mocked transport only. Candidates researched
     so far: Gemini API's free tier (audio input, 1500 req/day, no card
     required) is the most promising **but unverified** — it's built for
     multimodal QA/summarization, not confirmed to produce clean verbatim
     transcripts; that needs a real test call before trusting it for a
     live demo. Ollama Cloud's free models were checked and ruled out —
     none of them do speech-to-text at all (text-only chat models).
     MiniMax's STT API is real but not actually free ($60/1M characters,
     only small one-time trial credits). Hugging Face's free Inference
     API hosting real Whisper models was proposed as another zero-new-
     signup test (an `HF_TOKEN` already exists in `.env`) but not yet
     actually tested live.

- **Notes/flashcards appearing "soon after recording stops"** for a full
  60-minute lecture is the harder ask — T5 alone was measured at
  ~30-45+ minutes for that length even with today's fixes. Two honest
  paths discussed, neither built yet:
  1. Scope the *live* portion of the demo down to a shorter live-recorded
     segment (5-10 min) that can genuinely finish in a demo-feasible
     window, and separately show a full 60-minute lecture's *already
     pre-processed* output, clearly labeled as pre-processed rather than
     claimed as live.
  2. Build real incremental/streaming processing — run T1-T7
     continuously as chunks arrive *during* recording (not only after
     `is_final`), so only the last minute or two of content remains to
     process once recording stops. This is a genuine architecture change
     (the pipeline today only triggers once, at session finalization,
     see `src/workers/asr_worker.py`), not a config tweak — risky to
     build for the first time right before a live demo.

**Next step, if you're picking this up**: find out (a) how much lead time
exists before the demo, (b) test the Gemini free-tier audio endpoint (or
the HF Inference API Whisper endpoint) with a real short clip to confirm
whether it returns a clean, accurate, in-order transcript, and (c) get an
explicit decision from the user on which live-transcription option (GPU
reallocation vs. rented GPU vs. external ASR API) and which
notes-timing option (scope down vs. build incremental) to actually
implement — none of this has been decided yet, only researched.

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

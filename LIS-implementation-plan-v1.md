# Lecture Intelligence System — Master Implementation Plan
## 76 Integrated Stages · v1.0

**Implements:** SRS v1.0 · Architecture v1.0 · Stack Manifest v1.1 · GPU Revision v2.0 · Addendum v2.1
**Purpose:** the parent document from which per-stage specification documents are generated.
**Date:** September 2026

---

## How To Use This Document

Each stage is a **vertical slice** — it crosses database, application, ML, agent and infrastructure concerns together rather than completing one discipline at a time. A stage is only "done" when its schema, code, model work, tests and deployment all land. This is deliberate: horizontal layering produces six months of work with nothing demonstrable, and integration bugs discovered at the end.

### Stage record format

```
S## — Name
Deps:        stages that must complete first
SRS:         requirement IDs implemented
Scope:       what this stage changes, across all aspects, as one description
Deliverables: concrete artefacts
Tests:       T##.n — id, type, assertion
Exit:        the single condition that closes the stage
```

**Test types:** `U` unit · `I` integration (real PG/services via testcontainers) · `E` end-to-end · `V` eval/metric (statistical, thresholded) · `M` manual/human-judged · `S` security/licence · `P` performance

### Generating a spec document from a stage
Each stage expands into its own spec with: context and dependencies restated, interface contracts (SQL DDL, Pydantic schemas, API paths, prompt text), test cases expanded to given/when/then, rollback procedure, and observability additions. Stage records below carry enough structure that expansion is mechanical.

### Gates
Seven stages are **hard gates** — work downstream does not begin until they pass. Marked ⛔. Attempting to parallelise past a gate is the primary way this project fails.

---

## Block Overview

| Block | Stages | Theme | Gate |
|---|---|---|---|
| **B0** | S01–S06 | Foundation & feasibility | ⛔ S06 WER gate |
| **B1** | S07–S13 | Data foundation | — |
| **B2** | S14–S20 | Capture & ingestion | ⛔ S20 |
| **B3** | S21–S24 | Transcript integrity | — |
| **B4** | S25–S32 | Embedding & topic intelligence | ⛔ S29 P_k gate |
| **B5** | S33–S35 | Topic window & session routing | — |
| **B6** | S36–S40 | LLM serving infrastructure | — |
| **B7** | S41–S46 | Core agents: filter & synthesis | ⛔ S42 relevance gate |
| **B8** | S47–S49 | MVP close | ⛔ S49 MVP gate |
| **B9** | S50–S53 | Syllabus & coverage | — |
| **B10** | S54–S58 | Retrieval & assessment | — |
| **B11** | S59–S64 | Visual & multimodal | ⛔ S63 FR-4.9 boundary |
| **B12** | S65–S69 | Fine-tuning & data flywheel | — |
| **B13** | S70–S76 | Hardening & full acceptance | ⛔ S76 |

---

# BLOCK 0 — FOUNDATION & FEASIBILITY

### S01 — Repository, Tooling & CI Skeleton
**Deps:** —
**SRS:** infrastructure precondition
**Scope:** Monorepo with `src/` (api, workers, agents, ml, eval), `migrations/`, `notebooks/`, `docker/`, `config/`, `tests/`, `docs/adrs/`. Python 3.12 managed by `uv`. Ruff + mypy + pre-commit + gitleaks + sqlfluff. GitHub Actions running lint, type-check, unit tests, gitleaks, sqlfluff on PR. Conventional Commits enforced. ADR register initialised in `docs/adrs/` with ADR-001…014 from Architecture v1.0 plus ADR-015…018 for 4GB VRAM, hybrid LLM ladder, 8-bit quantization, local-first ASR/embedding.
**Deliverables:** repo skeleton · `pyproject.toml` · `.pre-commit-config.yaml` · CI workflow (`.github/workflows/ci.yml`) · ADR register (`docs/adrs/001-*.md` through `018-*.md`)
**Tests:**
- `T01.1` U — `uv sync` resolves on clean checkout, all three OS runners
- `T01.2` U — pre-commit passes on empty repo; fails on a deliberately unformatted file
- `T01.3` S — gitleaks detects a planted dummy secret and fails CI
- `T01.4` U — mypy strict passes on skeleton
- `T01.5` U — sqlfluff lint passes on migration files
- `T01.6` U — conventional commit check passes on valid messages, fails on invalid
**Exit:** a PR with a trivial change goes green through all CI gates.

### S02 — GPU Host Provisioning & CUDA Matrix Pin
**Deps:** S01
**SRS:** D-33 · v2.1 §5 · ADR-015
**Scope:** Provision the GPU host (Quadro T1000 Mobile, 4GB VRAM) with Ansible: NVIDIA driver 560.x (held/pinned via `apt-mark hold`), NVIDIA Container Toolkit, Docker Engine. Author the single **CUDA version matrix table** in `docs/cuda-matrix.md` fixing:
- NVIDIA Driver: 560.x
- CUDA Toolkit: 12.6
- cuDNN: 9.5.x
- PyTorch: 2.5.1+cu126
- flash-attn: 2.8.3
- bitsandbytes: 0.50.2
- faiss-gpu: 1.7.2
- ctranslate2: 4.8.2
- faster-whisper: 1.1.0
Every GPU Dockerfile references this matrix via build ARGs. Base image: `nvidia/cuda:12.6-cudnn-runtime-ubuntu22.04`. All models run with 8-bit quantization where needed (ADR-017).
**Deliverables:** Ansible playbook · `docs/cuda-matrix.md` · `docker/base-gpu.Dockerfile` · driver hold config
**Tests:**
- `T02.1` I — `docker run --gpus all base-gpu nvidia-smi` lists all cards
- `T02.2` I — `torch.cuda.is_available()` true; `torch.version.cuda` equals "12.6"
- `T02.3` I — flash-attn imports and runs a forward pass
- `T02.4` S — `apt-mark showhold` confirms driver held against unattended upgrade
- `T02.5` U — CI fails if any GPU Dockerfile pins a CUDA version differing from the matrix
- `T02.6` I — bitsandbytes 8-bit linear layer works: `import bitsandbytes; bitsandbytes.nn.Linear8bitLt`
**Exit:** all GPU containers build and see the GPUs; version matrix enforced in CI; 4GB VRAM constraint documented.

### S03 — Core Infrastructure Compose Stack
**Deps:** S02
**SRS:** FR-5.1, FR-5.2, FR-5.3
**Scope:** `docker-compose.yml` bringing up:
- PostgreSQL 17 + pgvector (PG-MAIN, port 5432)
- PostgreSQL 17 (PG-SYLLABUS, port 5433, separate instance)
- PgBouncer (port 6432, pools PG-MAIN)
- Valkey 8 (port 6379)
- MinIO (ports 9000/9001, buckets: lis-audio, lis-uploads, lis-generated, lis-exports, lis-eval with ILM)
- pgAdmin 4 (port 5050, both servers pre-registered via `servers.json`)
- Traefik v3 (ports 80/443/8080, mkcert local TLS via `docker/traefik/certs/`)
- Dozzle (logs, behind Traefik)
- Portainer CE (management, behind Traefik)
- Label Studio (port 8080, for S05 labelling, behind Traefik)
- MLflow (port 5000, tracking URI postgresql://pg-main, artifacts S3://lis-eval/mlflow/, behind Traefik)
Shared `models` volume (HF_HOME). Networks: `internal` (no egress, data/model services), `edge` (ingress only). PG tuned: `shared_preload_libraries=pg_stat_statements,pg_cron,pg_partman_bgw,vector`, `maintenance_work_mem=1GB`. Secrets via SOPS+age (`.sops.yaml`, age public keys in repo, private keys in 1Password).
**Deliverables:** compose file · PG configs (`docker/postgres/main.conf`, `syllabus.conf`) · init SQLs · pgAdmin server definitions · PgBouncer config · MinIO bucket init script · Traefik certs · SOPS config · Label Studio project templates
**Tests:**
- `T03.1` I — `docker compose up` reaches healthy on all services
- `T03.2` I — `CREATE EXTENSION vector; CREATE EXTENSION pg_partman;` succeed on PG-MAIN
- `T03.3` I — pgAdmin lists both PG-MAIN and PG-SYLLABUS
- `T03.4` S — a container on `internal` cannot reach the public internet (egress denied)
- `T03.5` I — MinIO bucket creation and object round-trip succeed
- `T03.6` I — HTTPS via mkcert works; `getUserMedia` secure-context requirement satisfied
- `T03.7` I — Label Studio accessible at `https://label.lis.local`, projects creatable
- `T03.8` I — MLflow UI accessible at `https://mlflow.lis.local`, experiments creatable
**Exit:** full local stack up, both databases reachable, no egress from internal network, Label Studio and MLflow operational.

### S04 — Real-Environment Audio Corpus
**Deps:** S03
**SRS:** Phase 0 / R-01
**Scope:** Record 8–10 real lectures in the actual target rooms with the actual intended device(s) (phone, USB mic, or any mic-enabled device). Capture varied conditions deliberately: front row vs back, quiet vs busy room, lecturer stationary vs moving, one session with heavy student discussion. Store raw in MinIO under `lis-eval/phase0/v1/{session_id}/audio.opus` (Opus 48kHz mono, ≤15MB/60min). Version with DVC (remote: MinIO `lis-eval` bucket). Record consent for each (NFR-S5) using template in `docs/consent-form.md` and metadata: room, device, position, duration, subject, consent_id. Consent forms stored separately (not in repo).
**Deliverables:** 8–10 sessions of raw audio · metadata manifest (`lis-eval/phase0/v1/manifest.json`) · DVC-tracked dataset · consent records
**Tests:**
- `T04.1` M — each recording has complete metadata and a consent record
- `T04.2` U — DVC checkout reproduces the dataset byte-identically
- `T04.3` M — corpus covers all declared condition variations (front/back, quiet/busy, stationary/moving, discussion)
**Exit:** versioned, consented, condition-diverse corpus available to the bake-off.

### S05 — Ground Truth & Labelling Infrastructure
**Deps:** S04
**SRS:** §12.4 eval framework
**Scope:** Deploy Label Studio (via docker-compose, S03). Hand-transcribe 5 hours of S04 audio to word level. On 30 lecture-equivalents (may reuse sessions), hand-mark **topic boundaries** and **topic labels**. Label 2,000 utterances for on/off-topic relevance with a written rubric (`docs/relevance-rubric.md`). Store all labels DVC-versioned in `lis-eval/labels/v1/`. Build `src/eval/harness.py` wrapping jiwer (WER), segeval (P_k, WindowDiff), scikit-learn (purity, V-measure) with a single `run_eval(dataset, predictions)` entry point. Inter-annotator agreement: if 2 annotators, Cohen's κ ≥ 0.75 on 200-utterance overlap; if 1 annotator, self-consistency check on 10% re-label.
**Deliverables:** Label Studio deployment (3 projects) · 5h word-level transcripts · boundary + topic labels · 2k relevance labels + rubric · eval harness (`src/eval/harness.py`)
**Tests:**
- `T05.1` U — eval harness reproduces a known WER on a synthetic reference/hypothesis pair
- `T05.2` U — segeval P_k on identical segmentations returns 0.0; on inverted returns >0.5
- `T05.3` M — inter-annotator agreement ≥ 0.75 Cohen's κ (or self-consistency if solo)
- `T05.4` U — label export is DVC-reproducible
**Exit:** all three label sets complete, eval harness validated against known inputs.

### S06 ⛔ — ASR & Embedding Bake-Off (HARD GATE)
**Deps:** S05
**SRS:** Phase 0 gate · R-01 · D-01 · D-02 · v2.0 §7.1 · ADR-015 · ADR-017 · ADR-018
**Scope:** Run on GPU host (4GB VRAM, sequential model loading) using 8-bit quantization where needed:
- **ASR Models** (via `faster-whisper` CTranslate2 backend, word-level timestamps):
  1. Whisper large-v3 (8-bit int8_float16)
  2. Whisper large-v3-turbo (FP16, ~2.5GB)
  3. Canary-Qwen 2.5B (8-bit via bitsandbytes)
  4. Parakeet TDT 1.1B (FP16, ~2.5GB)
- **Embedding Model**: Qwen3-Embedding-0.6B only (1024 dim, FP16 fits ~1.5GB; 4B/8B excluded per ADR-015)
- Measure WER per model per condition with `whisper-normalizer` applied.
- Embed hand-transcribed text (S05) with Qwen3-0.6B, cluster with BERTopic (UMAP+HDBSCAN), measure purity/V-measure against S05 topic labels.
- **Pairwise ASR disagreement**: quantify cross-model disagreement rate; correlate with transcription error (v2.0 §3.1).
- Log everything to MLflow (local, S03). No hosted API reference ceiling (ADR-018).
**Deliverables:** WER table (model × condition) · embedding/clustering quality table · disagreement analysis · **decisions locked: ASR model, embedding model=Qwen3-0.6B, embedding_dim=1024** · MLflow experiment · `config/models.yaml` frozen
**Tests:**
- `T06.1` V — **GATE: best ASR WER < 20% on the median condition** (quantized models)
- `T06.2` V — **GATE: clustering purity > 0.60 against hand labels** (Qwen3-0.6B, relaxed from 0.70 production target)
- `T06.3` V — worst-condition WER recorded; if >35%, escalate as capture problem not model problem
- `T06.4` V — ASR pairwise disagreement rate quantified; correlation between disagreement and error demonstrated
- `T06.5` M — chosen embedding dimension (1024) recorded and frozen in `config/models.yaml`
- `T06.6` I — all 4 ASR models load and infer sequentially without OOM on 4GB VRAM
**Exit:** **Both gate tests pass.** If T06.1 fails, the project halts here and addresses audio capture (external mic, placement, room) before any further stage. No downstream work begins on a failed gate.

---

# BLOCK 1 — DATA FOUNDATION

### S07 — Core Schema: Users, Subjects, Sessions
**Deps:** S03
**SRS:** FR-6.1, FR-6.3, FR-6.4
**Scope:** Alembic migration creating `users`, `subjects` (unique per user+name), `sessions` (with `session_type`, `status` state enum, `audio_quality`), and `agent_runs` (for FR-3.12 logging). SQLAlchemy 2.0 models, Pydantic v2 schemas, repository layer with asyncpg. FastAPI CRUD for subjects. pgTAP tests for constraints.
**Deliverables:** migration · models · schemas · repositories · `/subjects` API
**Tests:**
- `T07.1` I — subject creation; duplicate name for same user rejected; same name for different user allowed
- `T07.2` I — session `status` transitions constrained to the declared enum
- `T07.3` I — `ON DELETE CASCADE` from subject removes sessions
- `T07.4` U — Pydantic schema rejects malformed subject payloads
- `T07.5` I — Alembic `upgrade head` then `downgrade base` leaves a clean database
**Exit:** subjects and sessions creatable via API with all constraints enforced in the database.

### S08 — Subject Partitioning Machinery
**Deps:** S07
**SRS:** FR-6.2, FR-6.5 · ADR-010
**Scope:** Implement per-subject provisioning as a single transaction: insert subject, then `CREATE TABLE ... PARTITION OF` for each partitioned table, then create per-partition HNSW indexes. Wire pg_partman where it helps maintenance. Tables `utterances`, `segments`, `note_sections`, `note_provenance` declared `PARTITION BY LIST (subject_id)` with `subject_id` leading the primary key. Deprovisioning on subject delete drops partitions.
**Deliverables:** provisioning function · partition DDL templates · deprovision path
**Tests:**
- `T08.1` I — creating a subject produces all expected partitions and indexes
- `T08.2` I — `EXPLAIN` on a `subject_id`-filtered query shows **partition pruning** (only one partition scanned)
- `T08.3` I — query without `subject_id` filter is rejected by the repository layer
- `T08.4` I — subject deletion drops its partitions; other subjects' data intact
- `T08.5` P — provisioning a subject completes in < 2s
- `T08.6` I — 50 subjects provisioned concurrently without deadlock
**Exit:** subject isolation demonstrably enforced by the query planner, not application code.

### S09 — DB-1 Schema: Utterances & Segments
**Deps:** S08
**SRS:** FR-2.2, FR-2.3, FR-5.1
**Scope:** `utterances` (session, subject, seq, start_ms/end_ms, text, asr_confidence, speaker_tag, embedding vector(D), embed_model_ver NOT NULL, topic_id, is_relevant, filter_reason, outlier_score) and `segments` (start_utt, end_utt, topic_id, boundary_score, confidence). Dimension `D` taken from the S06 decision. HNSW index per partition. Repository with bulk insert and vector query methods.
**Deliverables:** migration · models · bulk-insert repository · vector query helpers
**Tests:**
- `T09.1` I — bulk insert of 1,000 utterances with embeddings succeeds
- `T09.2` I — `embed_model_ver` NOT NULL enforced; insert without it fails
- `T09.3` I — cosine similarity query returns correct nearest neighbours on a known fixture
- `T09.4` I — `UNIQUE (session_id, seq)` prevents duplicate sequence numbers
- `T09.5` P — vector query over 31k vectors in one partition returns in < 200ms (NFR-P6)
- `T09.6` I — `is_relevant` NULL by default (unfiltered state)
**Exit:** DB-1 accepts and queries a full session's worth of embedded utterances within the latency target.

### S10 — DB-2 Schema: Notes, Provenance & Assets
**Deps:** S08
**SRS:** FR-5.1, FR-7.1, FR-7.8
**Scope:** `note_sections` (subject, topic, session nullable for consolidated notes, heading, body_md, depth, ordinal, embedding, model_version), `note_provenance` (section→utterance many-to-many), `note_assets` (type, object_key, source_url, licence, match_score, is_ai_generated, ocr_text, ocr_confidence). **Constraint: `source_url` and `licence` NOT NULL when `asset_type='web_image'`.**
**Deliverables:** migration · models · repositories
**Tests:**
- `T10.1` I — note section with provenance links inserts and reads back
- `T10.2` I — web_image asset without licence is **rejected by constraint** (NFR-S7)
- `T10.3` I — deleting a note section cascades to provenance and assets
- `T10.4` I — `topics` centroid column stores and retrieves a vector
- `T10.5` U — `asset_type` check constraint rejects unknown types
**Exit:** notes and provenance persist; licence constraint enforced at database level.

### S11 — DB-3: Syllabus Instance & FDW Link
**Deps:** S03, S07
**SRS:** FR-5.3, FR-5.9 · v1.1 §3
**Scope:** Schema on the **separate** PG-SYLLABUS instance: `syllabus_items` (subject_id, parent_id self-ref, ordinal, title, description, embedding, source, source_session_id, coverage_status, covered_by topic_id array). Install `postgres_fdw` on PG-MAIN, create server + user mapping + foreign table so PG-MAIN can read syllabus items joined to local subjects. Register both in pgAdmin.
**Deliverables:** DB-3 migration · FDW server/mapping · foreign table · read-through repository
**Tests:**
- `T11.1` I — syllabus item hierarchy (parent/child) inserts and reads correctly
- `T11.2` I — FDW query from PG-MAIN returns rows from PG-SYLLABUS
- `T11.3` I — join between local `subjects` and foreign `syllabus_items` returns correct rows
- `T11.4` I — PG-SYLLABUS unavailable → FDW query fails cleanly with a handled error, not a hang
- `T11.5` S — FDW user mapping has read-only rights from PG-MAIN's side
**Exit:** DB-3 is a genuinely separate instance, readable from PG-MAIN via FDW, with graceful degradation.

### S12 — Row-Level Security & Auth Stub
**Deps:** S09, S10
**SRS:** NFR-S2, FR-6.5
**Scope:** JWT auth via fastapi-users (single-user pilot scope). Enable RLS on `subjects`, `sessions`, `utterances`, `segments`, `note_sections`; policies keying on `current_setting('app.user_id')`. Repository layer sets the session variable per request. Argon2id password hashing.
**Deliverables:** auth endpoints · RLS policies · per-request session variable middleware
**Tests:**
- `T12.1` I — user A cannot read user B's subjects **even with a direct SQL query** bypassing the API
- `T12.2` I — RLS blocks cross-user utterance reads
- `T12.3` U — JWT expiry honoured; expired token rejected
- `T12.4` S — password stored as Argon2id, never plaintext or reversible
- `T12.5` I — missing `app.user_id` session variable → zero rows, never all rows (fail-closed)
**Exit:** data isolation enforced by PostgreSQL independent of application correctness.

### S13 — Migration & Test Harness
**Deps:** S07–S12
**SRS:** engineering precondition
**Scope:** testcontainers-python fixture spinning real PG17+pgvector per test session. pgTAP suite for constraints/RLS/partitioning. Faker-based synthetic lecture transcript generator (realistic utterance lengths, topic shifts, off-topic interjections) so downstream stages can be developed and tested before real ASR output exists. CI runs integration tests on `main`.
**Deliverables:** test fixtures · pgTAP suite · synthetic transcript generator · CI integration job
**Tests:**
- `T13.1` I — testcontainers fixture provides a working pgvector database
- `T13.2` U — synthetic generator produces a transcript with N declared topics and verifiable boundary positions
- `T13.3` I — full pgTAP suite green
- `T13.4` U — `downgrade base` → `upgrade head` round-trip on a populated database preserves nothing (clean) and errors nowhere
**Exit:** any developer can run the full DB test suite locally in one command; synthetic data available for downstream development.

---

# BLOCK 2 — CAPTURE & INGESTION

### S14 — Object Store Layout & Lifecycle Policies
**Deps:** S03
**SRS:** NFR-S3, FR-4.11
**Scope:** Create buckets `lis-audio`, `lis-uploads`, `lis-generated`, `lis-exports`, `lis-eval` with the key schemes from Stack Manifest §6. Configure ILM: audio purged 30 days after session reaches `complete`; exports purged after 7 days; uploads and generated permanent. Storage client wrapper with presigned URL generation for direct client upload.
**Deliverables:** bucket provisioning script · ILM policies · storage client · presigned URL endpoint
**Tests:**
- `T14.1` I — object round-trip per bucket with correct key scheme
- `T14.2` I — ILM rule present and correctly expressed on `lis-audio` (policy asserted, not waited for)
- `T14.3` I — presigned PUT allows upload; expires correctly; cannot be reused after expiry
- `T14.4` S — presigned URL scoped to one key, cannot write elsewhere in the bucket
- `T14.5` I — audio purge simulated via forced lifecycle evaluation leaves transcripts intact
**Exit:** all buckets provisioned; audio retention enforced by policy rather than by a cron job that can be forgotten.

### S15 — Client Capture Application (PWA)
**Deps:** S03, S07
**SRS:** FR-1.1, FR-1.4, NFR-R1, NFR-S5
**Scope:** React + Vite + Tailwind PWA. Subject picker (from S07 API). Consent gate before recording with acknowledgement recorded. MediaRecorder + opus-recorder capturing 30s overlapping chunks. IndexedDB ring buffer via Workbox so chunks survive offline/backgrounding. Upload queue with retry and resume. Session start/stop UI, elapsed timer, recording indicator.
**Deliverables:** PWA app · consent flow · chunked recorder · offline queue · upload retry
**Tests:**
- `T15.1` E — 60-minute recording produces the expected chunk count with correct overlap
- `T15.2` E — **network disconnected mid-session → chunks buffer to IndexedDB → upload resumes and completes on reconnect** (NFR-R1)
- `T15.3` E — app backgrounded then foregrounded → recording continues, no chunk gap
- `T15.4` U — recording cannot start without consent acknowledgement
- `T15.5` U — recording cannot start without a subject selected (FR-6.3)
- `T15.6` E — browser tab closed mid-session → buffered chunks upload on next app open
- `T15.7` P — Opus output ≤ 15MB for a 60-minute session
**Exit:** a full lecture records reliably on a real phone in a real room, surviving network loss.

### S16 — Chunk Upload API & Stream Ingestion
**Deps:** S14, S15
**SRS:** FR-1.1, FR-1.4
**Scope:** `POST /sessions/{id}/chunks` accepting chunk + sequence + timestamp; writes to `lis-audio`; publishes `audio.chunk` to a Valkey Stream with consumer-group semantics. Idempotent on `(session_id, seq)` so client retries are safe. Session state machine transitions `created → recording`. SSE endpoint streaming session status to the client.
**Deliverables:** chunk endpoint · Valkey Stream producer · idempotency layer · SSE status stream
**Tests:**
- `T16.1` I — chunk uploaded, stored in MinIO, message present on stream
- `T16.2` I — **duplicate chunk `(session, seq)` is accepted and not double-published** (client retry safety)
- `T16.3` I — out-of-order chunk arrival stored correctly by sequence
- `T16.4` P — 20 concurrent sessions uploading chunks sustained without backlog growth (NFR-P7)
- `T16.5` I — SSE stream emits status transitions in order
- `T16.6` I — chunk for a `complete` session is rejected
**Exit:** chunks flow client → object store → stream, idempotently, at target concurrency.

### S17 — Audio Pre-Processing Chain
**Deps:** S16, S02
**SRS:** FR-1.3 · SR-01 mitigation · v1.1 §11
**Scope:** Worker consuming `audio.chunk`. Fixed chain: ffmpeg (16kHz mono, EBU R128 `loudnorm`) → DeepFilterNet denoise → **Silero VAD** dropping speechless regions. Emits processed audio plus a VAD map. This is the primary structural mitigation for Whisper hallucination — silence never reaches the ASR model.
**Deliverables:** preprocessing worker · chain implementation · VAD map output
**Tests:**
- `T17.1` U — output is 16kHz mono regardless of input format/rate
- `T17.2` V — loudnorm brings a deliberately quiet sample within target LUFS range (FR-1.3)
- `T17.3` V — **a chunk of pure silence produces zero speech regions** (the critical assertion)
- `T17.4` V — a chunk of HVAC-only noise produces zero speech regions
- `T17.5` V — quiet-but-real speech is retained, not gated out (false-negative check)
- `T17.6` V — DeepFilterNet improves SNR on a noisy sample from S04 corpus
- `T17.7` P — chain processes a 30s chunk in < 3s (keeps real-time factor < 1)
**Exit:** silence and steady noise are demonstrably removed before ASR; real quiet speech is preserved.

### S18 — Audio Quality Metrics & Operator Warning
**Deps:** S17
**SRS:** FR-1.5
**Scope:** Compute per-chunk SNR, VAD speech ratio, clipping rate; aggregate to a session `audio_quality` score written to `sessions`. When a rolling window falls below a configurable threshold, emit a warning over SSE so the operator can reposition the device **during** the lecture.
**Deliverables:** quality metric computation · threshold config · SSE warning · client warning UI
**Tests:**
- `T18.1` U — metrics computed correctly on fixtures of known SNR
- `T18.2` I — sub-threshold audio triggers a warning event on SSE
- `T18.3` I — warning appears in the client UI within 10s of onset
- `T18.4` I — session `audio_quality` persisted on completion
- `T18.5` U — threshold is configurable without code change
**Exit:** a badly-positioned microphone is surfaced to the user while the lecture is still running.

### S19 — ASR Worker (Primary Model)
**Deps:** S17, S06, S09
**SRS:** FR-2.1, FR-2.2, FR-7.8 · ADR-015 · ADR-017 · ADR-018
**Scope:** GPU worker running the S06-selected model via `faster-whisper` (CTranslate2 backend) with wav2vec2 forced alignment for **word-level timestamps** (required by provenance). Model loaded at production quantization: `large-v3-turbo` at FP16 or `large-v3` at int8_float16. Emits utterances with text, start/end ms, confidence. Persists to `utterances` in DB-1 with `embed_model_ver` from config. Session transitions `recording → transcribed`. **NFR-R3 durability gate: transcript is committed before any downstream stage is permitted to start.**
**Deliverables:** ASR worker (`src/workers/asr_worker.py`) · alignment · utterance persistence · state transition
**Tests:**
- `T19.1` V — WER on the S05 held-out set matches the S06 benchmark within tolerance
- `T19.2` I — word-level timestamps present and monotonically increasing
- `T19.3` I — utterances persisted with confidence, correct session/subject, `embed_model_ver`
- `T19.4` I — session status reaches `transcribed` only after commit
- `T19.5` I — worker killed mid-session → on restart, already-transcribed chunks are not reprocessed
- `T19.6` P — real-time factor < 1.0 (NFR-P1)
- `T19.7` I — **downstream flow trigger rejected if session status is not `transcribed`** (NFR-R3 gate assertion)
**Exit:** a real lecture becomes a durable, word-timestamped transcript in DB-1.

### S20 ⛔ — Anonymous Diarisation & Transcript Completion (GATE)
**Deps:** S19
**SRS:** FR-1.2, NFR-S4 · SRS §6 design note
**Scope:** pyannote.audio 3.x producing **anonymous** speaker tags (`SPK_A`, `SPK_B`) stored in `utterances.speaker_tag`. Tags are session-scoped metadata only: never linked to an identity, never persisted as a voiceprint, never used to gate content. Tags are dropped at note synthesis.
**Deliverables:** diarisation step · speaker_tag persistence · documented non-linkability
**Tests:**
- `T20.1` I — speaker tags assigned; multiple distinct speakers detected in a discussion-heavy session
- `T20.2` S — **no voiceprint, embedding or biometric template of any speaker is persisted anywhere** (NFR-S4) — verified by schema and storage audit
- `T20.3` S — speaker tags from two different sessions are **not** linkable to each other (tags are session-local)
- `T20.4` I — pipeline completes successfully with diarisation **disabled** (it is optional, never load-bearing)
- `T20.5` E — **GATE: end-to-end — record on device → chunks → preprocess → ASR → complete transcript in DB-1 with timestamps, confidence and tags**
**Exit:** **T20.5 passes.** The ingestion spine works end to end on real audio. This is the foundation every later block builds on.

---

# BLOCK 3 — TRANSCRIPT INTEGRITY

### S21 — Dual-ASR Ensemble
**Deps:** S20, S06
**SRS:** v2.0 §3.1 · SR-01
**Scope:** Run the second-place S06 model (e.g. Canary-Qwen) alongside the primary on every session. Align the two outputs by timestamp and compute per-utterance agreement. Store `asr_agreement` on `utterances`. Affordable only because inference is fixed-cost.
**Deliverables:** second ASR worker · output alignment · agreement score persistence
**Tests:**
- `T21.1` I — both models run; agreement score computed for every utterance
- `T21.2` V — agreement correlates negatively with word error on the S05 labelled set (the score is informative, not noise)
- `T21.3` I — if the secondary model fails, the pipeline proceeds on the primary alone with agreement NULL
- `T21.4` P — dual ASR completes within the NFR-P3 post-session budget
**Exit:** every utterance carries a cross-model agreement signal.

### S22 — Hallucination Detection
**Deps:** S21
**SRS:** SR-01 · FR-2.2
**Scope:** Three independent detectors: (a) **cross-model disagreement** — one model emits text where the other emits silence → discard; (b) **repetition detector** — n-gram loops characteristic of Whisper degeneration; (c) **VAD contradiction** — text present in a region VAD marked speechless. Flagged utterances marked `is_relevant=false, filter_reason='asr_hallucination'` (soft delete, never removed).
**Deliverables:** three detectors · flagging logic · hallucination metrics
**Tests:**
- `T22.1` V — **a 60s silence injected into real audio produces zero retained utterances** (the canonical Whisper failure)
- `T22.2` V — a deliberately repeated-phrase sample is caught by the repetition detector
- `T22.3` V — detectors' false-positive rate on real speech < 2% (must not eat real content)
- `T22.4` I — flagged utterances are **marked, not deleted** (FR-2.15)
- `T22.5` V — measured hallucination rate on the S04 corpus recorded as a tracked metric
**Exit:** the canonical hallucination failure modes are caught and auditable.

### S23 — Session Lifecycle State Machine
**Deps:** S20
**SRS:** NFR-R5, NFR-R6
**Scope:** Explicit state machine `created → recording → transcribed → processing → complete | failed`, with transitions enforced in one place and illegal transitions rejected. Failure marking is explicit and never silent. Retry queue for `failed` sessions. `notes_ready` flag separate from status.
**Deliverables:** state machine · transition guards · retry queue · failure events
**Tests:**
- `T23.1` U — every illegal transition rejected (exhaustive matrix test)
- `T23.2` I — a stage failure sets `failed`, never `complete` (NFR-R5)
- `T23.3` I — `failed` session appears in the retry queue
- `T23.4` I — reprocessing a `failed` session from the retained transcript succeeds without re-capture (NFR-R4)
- `T23.5` I — concurrent transition attempts resolve to one winner (no split state)
**Exit:** no session can be silently half-processed; every failure is visible and recoverable.

### S24 — Transcript Read API & Client View
**Deps:** S22, S23
**SRS:** FR-2.3, FR-7.8 precursor
**Scope:** Paginated transcript API filtered by session/subject with relevance and hallucination flags exposed. Client transcript view with wavesurfer.js audio scrubbing synced to word timestamps — tap a line, hear it. This is the first user-visible deliverable and validates timestamp quality by eye.
**Deliverables:** transcript API · client transcript view · audio-synced playback
**Tests:**
- `T24.1` I — pagination correct and stable across pages
- `T24.2` I — API returns only the requesting user's transcripts (RLS verified end to end)
- `T24.3` E — clicking an utterance plays the correct audio position within 500ms accuracy
- `T24.4` M — human review confirms transcript readability and timestamp alignment on 3 real sessions
- `T24.5` P — transcript page loads in < 1s for a 60-minute session
**Exit:** users can read and audio-scrub their own lecture transcripts. **Phase 1 of the SRS is complete and independently useful.**

---

# BLOCK 4 — EMBEDDING & TOPIC INTELLIGENCE

### S25 — Embedding Service & Version Governance
**Deps:** S06, S09
**SRS:** FR-5.7, R-11 · v1.0 §19 · ADR-015
**Scope:** HF TEI (or sentence-transformers fallback) serving Qwen3-Embedding-0.6B at frozen 1024 dimension (only model fitting 4GB VRAM). Every write stamps `embed_model_ver`; every retrieval filters on the active version. Version registry in `config/models.yaml`. Backfill flow skeleton for future model changes (per-subject, resumable). Instruction prefix applied for clustering vs retrieval task modes.
**Deliverables:** TEI service · embedding client · version registry · backfill flow skeleton
**Tests:**
- `T25.1` I — TEI returns vectors of exactly 1024 dimensions
- `T25.2` I — write without `embed_model_ver` rejected
- `T25.3` I — retrieval with two versions present returns **only** active-version vectors
- `T25.4` I — backfill flow re-embeds one subject and switches its active version atomically
- `T25.5` P — 1,000 utterances embedded in < 60s
- `T25.6` U — instruction prefix applied correctly for clustering vs retrieval task modes
**Exit:** embeddings are versioned such that a model change is a resumable migration, not an outage.

### S26 — Context-Window Embedding
**Deps:** S25
**SRS:** ML-4
**Scope:** Embed **overlapping blocks** of W preceding utterances plus the current one, rather than isolated utterances — single ASR utterances are too sparse and noisy to embed meaningfully. W configurable; default from S06 experimentation.
**Deliverables:** windowing implementation · W config · comparative benchmark
**Tests:**
- `T26.1` U — window construction correct at transcript start (fewer than W predecessors) and end
- `T26.2` V — **windowed embeddings produce higher clustering purity than isolated-utterance embeddings** on S05 labels (justifies the complexity)
- `T26.3` U — W is configurable; W=0 degenerates to isolated embedding
- `T26.4` P — windowing adds < 20% to embedding time
**Exit:** windowed embedding measurably outperforms naive embedding; W chosen on evidence.

### S27 — Prefect Setup & Embedding Task (T1)
**Deps:** S26, S23
**SRS:** FR-5.6, NFR-R4, NFR-R6 · ADR-001
**Scope:** Prefect server + worker pools (`ml-pool`, `llm-pool`). `process_session` flow with the NFR-R3 assertion gate at entry. Task T1 `embed_utterances`, cached on `(session_id, embed_model_ver)`. Flow triggered by the `session.transcribed` event.
**Deliverables:** Prefect deployment · flow skeleton · T1 task · event trigger · caching
**Tests:**
- `T27.1` I — flow triggers automatically on `session.transcribed`
- `T27.2` I — **flow refuses to start if session status is not `transcribed`** (NFR-R3)
- `T27.3` I — re-running the flow **reuses cached T1** results (no re-embedding)
- `T27.4` I — changing `embed_model_ver` invalidates the cache and re-embeds
- `T27.5` I — worker killed mid-task → task retried, no duplicate rows (idempotency, NFR-R6)
- `T27.6` I — flow failure marks session `failed` and emits the event
**Exit:** the orchestrated pipeline exists, is event-driven, cached, and idempotent.

### S28 — Boundary Detection (Segmentation)
**Deps:** S26
**SRS:** FR-2.8, FR-5.9, ML-7 · ADR-006 · §12.2
**Scope:** Custom TextTiling-style sequential segmentation over windowed embeddings: adjacent-block cosine similarity with an adaptively determined threshold. Produces **ordered, contiguous, non-overlapping** segments written to `segments` with `boundary_score`. This is the piece no library does well on ASR output.
**Deliverables:** segmentation algorithm · segments persistence · boundary scores
**Tests:**
- `T28.1` U — **segments are contiguous, ordered and non-overlapping** (Hypothesis property test over random transcripts)
- `T28.2` U — every utterance belongs to exactly one segment
- `T28.3` V — on synthetic transcripts with known boundaries (S13 generator), boundaries recovered within ±2 utterances
- `T28.4` V — a single-topic lecture yields one segment, not spurious splits
- `T28.5` P — segmentation of 1,000 utterances completes in < 10s
**Exit:** segmentation produces structurally valid, ordered segments on both synthetic and real transcripts.

### S29 ⛔ — Segmentation Evaluation (HARD GATE)
**Deps:** S28, S05
**SRS:** Phase 2 gate · §12.4
**Scope:** Evaluate segmentation against the 30 hand-marked lectures from S05 using **P_k and WindowDiff**. Tune the adaptive threshold. Compare against baselines: fixed-window, random, and one published method for reference.
**Deliverables:** evaluation report · tuned threshold · baseline comparison
**Tests:**
- `T29.1` V — **GATE: P_k < 0.30 on the held-out set**
- `T29.2` V — WindowDiff recorded alongside P_k
- `T29.3` V — **beats random and fixed-window baselines by a clear margin** (guards against a metric that passes trivially)
- `T29.4` V — performance reported per condition (discussion-heavy vs monologue)
**Exit:** **T29.1 and T29.3 pass.** If not, segmentation approach is revised before clustering is built on top of it — clustering inherits segmentation error directly.

### S30 — Topic Clustering
**Deps:** S29, S27
**SRS:** FR-2.6, FR-5.3, FR-5.8, ML-5 · §12.2
**Scope:** Task T3. Mean-pool each segment's member embeddings, then cluster **segment** embeddings (not raw utterances) with UMAP + HDBSCAN via BERTopic. Persist `topics` rows with centroid and keywords. **Store the HDBSCAN outlier score on each utterance** — it feeds A1 later. Segment-first-then-cluster ordering per §12.2.
**Deliverables:** T3 task · BERTopic pipeline · topics persistence · outlier scores
**Tests:**
- `T30.1` I — clustering produces topics; each segment assigned a topic or marked outlier
- `T30.2` V — **purity > 0.70 against S05 topic labels** (production target)
- `T30.3` V — **a session covering two distinct topics yields ≥ 2 clusters** (FR-5.8)
- `T30.4` I — clustering scoped strictly within one subject; no cross-subject vectors retrieved (FR-2.10, FR-6.5)
- `T30.5` I — outlier scores persisted on utterances
- `T30.6` P — clustering 31k vectors completes in < 5 min
- `T30.7` I — topic assignments are contiguous within a segment (inherited from S28)
**Exit:** topics discovered within a subject at target purity, with outlier scores available downstream.

### S31 — Topic Labelling & Keyword Extraction
**Deps:** S30
**SRS:** FR-2.7, ML-6, ML-8
**Scope:** c-TF-IDF + KeyBERT for **side keywords** per cluster. LLM labels each cluster from its top-N representative utterances plus keywords; labels are human-editable. Labels and keywords written to `topics`.
**Deliverables:** keyword extraction · LLM labelling · label edit API
**Tests:**
- `T31.1` V — extracted keywords judged relevant by human review on 20 clusters (≥ 80% acceptable)
- `T31.2` M — LLM topic labels judged accurate on 20 clusters (≥ 80%)
- `T31.3` I — user label edit persists and is not overwritten by re-clustering
- `T31.4` U — labelling handles a single-member cluster without error
- `T31.5` I — labelling failure leaves a placeholder label; pipeline continues
**Exit:** topics carry human-meaningful labels and keywords.

### S32 — Cross-Session Topic Identity
**Deps:** S31
**SRS:** FR-5.3, FR-5.4, FR-5.5, FR-5.10, FR-5.11 · ADR-010
**Scope:** For each new segment, nearest-centroid match against the subject's existing topics via pgvector. Above threshold → link to existing topic (FR-5.4); below → create new topic (FR-5.5). Incremental centroid update. Full re-cluster flow triggered every N sessions (default 10; tighter for sessions 2–5 per §12.5 cold start).
**Deliverables:** centroid matching · link/create logic · incremental centroid update · re-cluster flow
**Tests:**
- `T32.1` V — **a topic taught across three separate sessions is recognised as one topic, not three** (AC-4)
- `T32.2` V — a genuinely new topic creates a new partition rather than being force-matched
- `T32.3` I — centroids update incrementally and correctly after each session
- `T32.4` I — full re-cluster preserves user-edited labels (S31)
- `T32.5` I — matching queries never cross subject boundaries
- `T32.6` V — threshold sensitivity analysed; chosen value justified against S05 labels
- `T32.7` P — matching a session's segments against 50 existing topics in < 1s
**Exit:** topic identity accumulates correctly across a semester within a subject.

---

# BLOCK 5 — TOPIC WINDOW & SESSION ROUTING

### S33 — Greeting Keywords & Topic Window
**Deps:** S30
**SRS:** FR-2.3, FR-2.4, FR-2.5, FR-2.9
**Scope:** Detect configurable greeting keywords ("good morning/afternoon/evening" and equivalents) as a **session-start/boundary signal** — never to classify or exclude a speaker. Run a provisional clustering pass over the first 10 minutes to establish early topic candidates, surfaced to the client for a "does this look like the right subject?" check. **The post-session full-transcript pass (S30) remains authoritative per FR-2.9.**
**Deliverables:** keyword detector · provisional window pass · early feedback to client
**Tests:**
- `T33.1` U — greeting keywords detected across phrasings and languages configured
- `T33.2` I — **greeting detection never sets or influences `speaker_tag` or relevance** (explicit negative assertion — this reverses the original design and must not regress)
- `T33.3` I — provisional topics available within 60s of the 10-minute mark (NFR-P2)
- `T33.4` V — **provisional result differs from final result on at least one real session, and the final result is used** (proves FR-2.9 authority)
- `T33.5` I — a session shorter than 10 minutes completes without error
**Exit:** early topic feedback delivered; post-session pass demonstrably authoritative.

### S34 — Transition Cue Detection
**Deps:** S28, S31
**SRS:** FR-2.8, ML-9
**Scope:** Curated high-precision pattern set for explicit forward references ("next we'll cover", "moving on to", "that completes", "before the break") plus LLM confirmation of candidates. Cues **boost** boundary scores in S28 rather than overriding them — a second independent signal.
**Deliverables:** cue pattern set · LLM confirmation step · boundary score boosting
**Tests:**
- `T34.1` U — each pattern matches its intended phrasings
- `T34.2` V — precision > 0.85 on the S05 corpus (high-precision by design; recall may be low)
- `T34.3` V — adding cues **improves P_k** versus S29 baseline (must earn its place)
- `T34.4` I — a cue in the middle of a coherent topic does not force a spurious split (it boosts, not overrides)
**Exit:** transition cues measurably improve segmentation without introducing false splits.

### S35 — Session Type Classification & Routing
**Deps:** S34, S36
**SRS:** FR-2.20, FR-2.21
**Scope:** Classify each session as `content` / `syllabus` / `mixed` from its transcript, with ensemble voting (cheap, high-consequence decision per v2.0 §4.1) and an operator override at session start. **For `mixed`, route segments individually** — a first lecture covering syllabus then teaching is the common case, not an exception.
**Deliverables:** classifier · ensemble vote · operator override · segment-level routing
**Tests:**
- `T35.1` V — classification accuracy > 0.90 on labelled sessions
- `T35.2` I — **a mixed session routes its syllabus segments to DB-3 and its content segments to DB-2 from one transcript** (FR-2.21)
- `T35.3` I — operator override takes precedence over classification
- `T35.4` I — ensemble disagreement flags the session for review rather than guessing
- `T35.5` I — misclassification is correctable post hoc and triggers re-routing
**Exit:** session type determined reliably; mixed sessions handled without losing either half.

---

# BLOCK 6 — LLM SERVING INFRASTRUCTURE

### S36 — Local LLM Serving
**Deps:** S02
**SRS:** FR-3.1, FR-3.14 · v2.0 §2 · ADR-015 · ADR-016
**Scope:** vLLM serving Tier 1 local model (Phi-3-mini-3.8B-4bit or Qwen2.5-3B-4bit, AWQ quantized, ~2.5GB VRAM) with OpenAI-compatible endpoint. Explicit `--gpu-memory-utilization=0.85` and fixed service start order (vLLM first) to prevent VRAM fragmentation. **No secondary base model on GPU** (4GB constraint); consensus voting uses Tier 2 CPU llama.cpp (ADR-016). Tier 1 model pinned in `config/models.yaml`.
**Deliverables:** vLLM service · model pins · VRAM allocation config · start-order enforcement · `config/models.yaml` Tier 1 entry
**Tests:**
- `T36.1` I — completion endpoint responds correctly
- `T36.2` I — **all co-resident services (ASR, TEI, LLM) start successfully together in the declared order** (fragmentation regression test)
- `T36.3` P — throughput meets the concurrency needed for NFR-P3
- `T36.4` I — service restart recovers without manual intervention
- `T36.5` P — VRAM headroom remains after all services loaded (no OOM at peak, <4GB total)
- `T36.6` I — Tier 1 model loads at 4-bit AWQ, not FP16
**Exit:** local LLM serves reliably as Tier 1, co-resident with ASR/TEI on 4GB VRAM.

### S37 — LLM Router & Failover Ladder
**Deps:** S36
**SRS:** FR-3.9, FR-3.10, FR-3.14 · §8.1 · ADR-016
**Scope:** LiteLLM proxy implementing the five-tier hybrid ladder (local-first):
- **Tier 1**: Local GPU (vLLM) — Phi-3-mini-3.8B-4bit / Qwen2.5-3B-4bit
- **Tier 2**: Local CPU (llama.cpp) — Llama-3-7B-4bit / Mistral-7B-4bit (system RAM)
- **Tier 3**: Hosted API — OpenAI GPT-4o-mini / Anthropic Haiku
- **Tier 4**: Hosted API (cheap) — Together.ai / Fireworks / Groq
- **Tier 5**: **FAIL** — mark session `failed`, enqueue for retry (never `complete`)
Triggers per FR-3.10: HTTP error, timeout (60s T1, 120s T2, 30s T3/4), rate limit, schema-invalid output. Tier used recorded per invocation in `agent_runs.tier`.
**Deliverables:** LiteLLM config (`config/litellm.yaml`) · ladder definition · Tier-5 failure handler
**Tests:**
- `T37.1` I — each trigger condition independently causes descent to the next tier
- `T37.2` E — **primary model container killed mid-flow → session completes via fallback, not failed** (AC-8)
- `T37.3` E — **all tiers exhausted → session marked `failed`, never `complete`; fully reprocessable from retained transcript** (AC-9, Tier 5)
- `T37.4` I — timeout budget is configurable per agent
- `T37.5` I — tier used is recorded per invocation in `agent_runs.tier`
- `T37.6` I — rate-limit response descends without retry-storming the failing tier
**Exit:** no single model failure can lose a session; total failure is explicit and recoverable.

### S38 — Structured Output & Schema Registry
**Deps:** S37
**SRS:** FR-3.13 · v2.0 §2.4
**Scope:** Pydantic output schema per agent (A1–A6) in one registry. **Outlines/XGrammar grammar-constrained decoding on local models** so invalid JSON is structurally impossible; Instructor with bounded retry for hosted tiers. One bounded retry then failover per FR-3.13.
**Deliverables:** schema registry · constrained decoding integration · retry/failover wiring
**Tests:**
- `T38.1` I — **local model output is always schema-valid across 500 varied generations** (grammar constraint assertion)
- `T38.2` I — a deliberately malformed hosted-tier response triggers exactly one retry, then failover
- `T38.3` U — every agent has a registered schema; CI fails if one is missing
- `T38.4` U — schema change is detected by CI as a breaking-change warning
- `T38.5` I — schema validation failure is logged with the offending output for debugging
**Exit:** agent outputs are always schema-valid or explicitly failed — never silently malformed.

### S39 — Observability: Tracing & Cost Attribution
**Deps:** S38
**SRS:** FR-3.12, NFR-C1
**Scope:** LangFuse deployed. Every agent invocation traced with agent ID, model, tier, prompt version, token counts, latency, outcome, and `trace_id` propagated from the Prefect flow through each LangGraph node. `agent_runs` table as the queryable system of record for cost. OpenTelemetry spans on Prefect tasks and LangGraph nodes.
**Deliverables:** LangFuse deployment · tracing instrumentation · `agent_runs` writes · cost query
**Tests:**
- `T39.1` I — every agent call produces a LangFuse trace and an `agent_runs` row
- `T39.2` I — `trace_id` correlates a full session's spans end to end
- `T39.3` I — per-session cost computable by SQL from `agent_runs` (NFR-C1)
- `T39.4` S — traces exclude raw transcript content beyond debugging need (NFR-S10)
- `T39.5` I — **trace graph contains no A3→A5 or A5→A3 edge** (AC-15 precursor assertion, automated)
**Exit:** every LLM call is traceable and costed; agent isolation is machine-verifiable.

### S40 — Prompt Versioning & Regression Testing
**Deps:** S39
**SRS:** FR-3.11
**Scope:** Prompts versioned in LangFuse (or git files) and referenced by version, not inlined. promptfoo regression suite per agent with golden cases. CI runs the suite whenever a prompt changes and blocks merge on regression. Per-agent model/temperature configurable without code change.
**Deliverables:** prompt registry · promptfoo suites · CI gate · per-agent config
**Tests:**
- `T40.1` U — changing a prompt without bumping its version fails CI
- `T40.2` I — promptfoo suite runs in CI and reports per-case results
- `T40.3` I — a deliberately degraded prompt is **caught by the regression suite** (the suite has teeth)
- `T40.4` I — agent model swapped by config alone, no code change
- `T40.5` I — prompt version recorded on every `agent_runs` row
**Exit:** prompt changes cannot silently degrade output quality.

---

# BLOCK 7 — CORE AGENTS: FILTERING & SYNTHESIS

### S41 — A1 Relevance Filter
**Deps:** S38, S30, S32
**SRS:** FR-2.13, FR-2.14, FR-2.15, FR-2.16, FR-3.3
**Scope:** A1 classifies utterances (batched) as on/off-topic against the identified topic. **HDBSCAN outlier score supplied as a prompt feature, not a gate** (v2.0 §3.3 — GPUs remove the need for ADR-011's pre-filter). Filtering applies identically to lecturer and student speech (FR-2.14). Decisions written as `is_relevant` + `filter_reason` — **soft delete, never removal** (FR-2.15).
**Deliverables:** A1 agent · prompt · batching · soft-delete writes · decision rationale
**Tests:**
- `T41.1` I — every utterance receives a decision and a rationale
- `T41.2` I — **a topically relevant student question is RETAINED** (AC-5 — the core FR-2.14 assertion)
- `T41.3` I — **an off-topic lecturer aside is DISCARDED** (symmetry assertion — filtering is topic-based, not speaker-based)
- `T41.4` I — discarded utterances remain in DB-1 marked, not deleted (FR-2.15)
- `T41.5` I — rationale is machine-readable for threshold tuning (FR-2.16)
- `T41.6` U — batch boundaries do not change individual decisions
**Exit:** relevance filtering operates on topic, symmetrically across speakers, reversibly.

### S42 ⛔ — A1 Evaluation & Threshold Calibration (HARD GATE)
**Deps:** S41, S05
**SRS:** §12.4 · asymmetric-cost design note
**Scope:** Evaluate A1 against the 2,000 hand-labelled utterances. **Tune for high precision on the discard decision** — wrongly keeping chatter yields slightly noisy notes; wrongly discarding a key explanation yields silently incomplete notes the user cannot detect. Targets from §12.4: precision on discard > 0.90, recall > 0.80.
**Deliverables:** evaluation report · calibrated thresholds · per-category error analysis
**Tests:**
- `T42.1` V — **GATE: precision on discard > 0.90**
- `T42.2` V — **GATE: recall on off-topic > 0.80**
- `T42.3` V — error analysis by utterance category (student question, admin, aside, tangent, core content)
- `T42.4` V — **zero core-content utterances discarded in the held-out set** (the unacceptable failure)
- `T42.5` V — outlier score confirmed as an informative feature (ablation shows it helps)
**Exit:** **T42.1, T42.2 and T42.4 pass.** A1 does not silently delete teaching.

### S43 — A1 Ensemble Voting
**Deps:** S42, S36
**SRS:** v2.0 §4.2 · founding multi-LLM consensus intent
**Scope:** For utterances where the outlier score is ambiguous (~15%), run 2–3 models independently and vote. **Split vote → KEEP and flag for review**, honouring the asymmetric cost. This is the founding "multiple LLMs reaching consensus" idea, now affordable — applied where disagreement carries real signal.
**Deliverables:** voting logic · ambiguity band config · review flagging
**Tests:**
- `T43.1` V — ensemble improves discard precision over single-model (S42) baseline
- `T43.2` I — split vote results in retention plus a review flag, never discard
- `T43.3` I — ambiguity band is configurable; set to zero degenerates to single-model
- `T43.4` I — models vote **independently** — no model sees another's output
- `T43.5` P — ensemble stays within the NFR-P3 processing budget
**Exit:** consensus voting measurably improves filtering on the cases where it matters.

### S44 — A2 Note Synthesis
**Deps:** S43, S32
**SRS:** FR-3.4, FR-7.1, FR-7.8 · v2.0 §3.2
**Scope:** A2 receives the **full session transcript plus all segments plus prior session notes plus syllabus context** in one call (v2.0 §3.2 — cheap locally, and yields cross-segment coherence). Emits structured sections with heading, `body_md`, depth, ordinal, and `source_utt_ids` for provenance. **Prompted to prefer Mermaid/KaTeX over requesting an image** (v1.1 §20, D-25).
**Deliverables:** A2 agent · full-context prompt · section schema · provenance emission · Mermaid/KaTeX preference
**Tests:**
- `T44.1` I — notes produced with valid hierarchy and ordering
- `T44.2` I — **every section carries at least one provenance utterance ID** (FR-7.8)
- `T44.3` I — provenance IDs all reference utterances marked `is_relevant=true`
- `T44.4` M — human review: notes accurate, complete, well-structured (≥ 4/5 on 10 sessions, §12.4)
- `T44.5` V — **full-context synthesis rated better than segment-by-segment** on a head-to-head human comparison (justifies the approach)
- `T44.6` I — emitted Mermaid blocks are syntactically valid
- `T44.7` I — emitted KaTeX renders without error
- `T44.8` I — no discarded utterance content appears in notes
**Exit:** notes are coherent, provenance-linked, and human-rated at target quality.

### S45 — Note Persistence & Idempotency
**Deps:** S44, S10
**SRS:** FR-5.5, FR-5.6, NFR-R6
**Scope:** Task T5 writing sections + provenance to DB-2 as an **idempotent upsert** keyed on `(session_id, topic_id, ordinal)`. **Enforce FR-5.6: reject any DB-2 write lacking a corresponding DB-1 record.** Section embeddings written for later retrieval. Session → `complete`, `notes_ready=true`.
**Deliverables:** T5 task · idempotent upsert · FR-5.6 guard · section embedding
**Tests:**
- `T45.1` I — **re-running the flow does not duplicate note sections** (NFR-R6)
- `T45.2` I — **DB-2 write for a session with no DB-1 record is rejected** (AC-6, FR-5.6 assertion)
- `T45.3` I — section embeddings present and queryable
- `T45.4` I — partial write failure rolls back cleanly; no orphaned provenance
- `T45.5` I — `notes_ready` set only after successful commit
**Exit:** notes persist idempotently and cannot exist without their source transcript.

### S46 — Note Read API & Client View
**Deps:** S45
**SRS:** FR-7.1, FR-7.2, FR-7.8
**Scope:** Notes API by session and by topic (consolidated across sessions, FR-7.2). Client note view rendering Markdown + KaTeX + Mermaid, with **provenance affordance**: tap a section → jump to the source transcript position and audio. Topic navigation per subject.
**Deliverables:** notes API · consolidated-topic endpoint · client note view · provenance navigation
**Tests:**
- `T46.1` I — per-session notes returned correctly
- `T46.2` I — **consolidated topic notes merge content across all sessions containing that topic** (FR-7.2)
- `T46.3` E — provenance tap navigates to correct transcript utterance and audio position
- `T46.4` E — KaTeX and Mermaid render correctly in the client
- `T46.5` I — RLS verified: no cross-user note access
- `T46.6` P — note page loads in < 3s (NFR-P4)
**Exit:** users read topic-organised, verifiable notes. **The core product exists.**

---

# BLOCK 8 — MVP CLOSE

### S47 — Full Flow Wiring & Re-Runnability
**Deps:** S46
**SRS:** FR-5.6, NFR-R4, NFR-R6 · ADR-001
**Scope:** Wire T1–T7 into the complete `process_session` flow with per-task cache keys on `(session_id, embed_model_ver, prompt_version)`. Wire the LangGraph T4 subgraph with `session_type` routing. Implement the `uploads.ready` partial re-run path (re-runs only the visual branch, reusing T1–T3 cache) ahead of Block 11. Emit `session.complete` / `session.failed`.
**Deliverables:** complete flow · cache keys · T4 subgraph wiring · partial re-run path · events
**Tests:**
- `T47.1` E — full flow runs end to end on a real session, transcript → notes
- `T47.2` I — re-run after a prompt version bump **recomputes only affected tasks**
- `T47.3` I — re-run after an embedding version bump recomputes from T1
- `T47.4` I — killing the worker at each of T1–T7 in turn → flow resumes correctly from that point
- `T47.5` I — partial re-run (uploads path) reuses T1–T3 cache
- `T47.6` P — **60-minute lecture processed end to end in < 15 min P90** (NFR-P3)
- `T47.7` I — events emitted on both success and failure
**Exit:** the pipeline is durable, resumable and selectively re-runnable at every stage.

### S48 — Hybrid Search
**Deps:** S46
**SRS:** **FR-7.10 (new)** · v2.1 §4
**Scope:** Add generated `tsvector` columns with GIN indexes to `utterances` and `note_sections`. Implement hybrid retrieval fusing lexical `ts_rank` and pgvector cosine via **Reciprocal Rank Fusion**. Search API and client search UI scoped to a subject. Closes the gap where no prior document specified any exact-term retrieval path.
**Deliverables:** tsvector columns + GIN indexes · RRF query · search API · client search
**Tests:**
- `T48.1` I — **exact phrase query ("this will be on the exam") returns the correct utterance** — the case dense retrieval fails
- `T48.2` I — conceptual query ("the thing about reaction rates") returns semantically correct results
- `T48.3` V — hybrid **outperforms both vector-only and lexical-only** on a 50-query labelled set
- `T48.4` I — search never crosses subject boundaries
- `T48.5` P — hybrid query returns in < 300ms P95
- `T48.6` I — search covers both transcripts and notes
**Exit:** users can find content by remembered wording as well as by meaning.

### S49 ⛔ — MVP Acceptance (HARD GATE)
**Deps:** S47, S48
**SRS:** AC-1 … AC-11
**Scope:** Encode SRS acceptance criteria AC-1 through AC-11 as an executable pytest suite run against a real deployment with real recorded lectures. Pilot with 3–5 real users for two weeks of actual lectures. Collect structured feedback.
**Deliverables:** AC-1…AC-11 automated suite · pilot deployment · feedback report
**Tests:**
- `T49.1` E — AC-1: subject declared, session recorded against it
- `T49.2` E — AC-2: 60-min lecture → complete transcript, WER within the S06 gate
- `T49.3` E — AC-3: two-topic session split into two ordered segments
- `T49.4` E — AC-4: topic across three sessions recognised as one
- `T49.5` E — AC-5: off-topic chatter excluded; relevant student question retained
- `T49.6` E — AC-6: notes post-session only; no DB-2 row without DB-1
- `T49.7` E — AC-7: every note section traces to source utterances and timestamps
- `T49.8` E — AC-8: primary LLM killed → completes via fallback
- `T49.9` E — AC-9: all tiers exhausted → `failed`, fully reprocessable
- `T49.10` E — AC-10: no cross-subject retrieval
- `T49.11` P — AC-11: processing < 15 min P90
- `T49.12` M — pilot users report the notes are usable for study (structured survey)
**Exit:** **All eleven AC tests pass and pilot feedback is positive.** MVP complete. This is the decision point for continuing to Blocks 9–13.

---

# BLOCK 9 — SYLLABUS & COVERAGE

### S50 — A6 Syllabus Extraction
**Deps:** S35, S11, S38
**SRS:** FR-2.17, FR-2.18, FR-2.19, FR-3.8
**Scope:** A6 extracts structured syllabus items from a syllabus-lecture transcript: topic/module list, ordering, assessment structure, references, stated schedule. **A6 is the sole writer to DB-3.** The transcript path is identical to any other lecture (FR-2.17) — only the downstream routing differs.
**Deliverables:** A6 agent · extraction schema · DB-3 write path · write-authority enforcement
**Tests:**
- `T50.1` I — **a syllabus lecture follows the identical capture/ASR path as a content lecture** (FR-2.17 assertion)
- `T50.2` I — extracted items land in DB-3, **not** DB-2 (AC-12)
- `T50.3` I — item hierarchy and ordinals correct
- `T50.4` S — **no agent other than A6 can write to DB-3** (permissions verified at DB level, FR-3.8)
- `T50.5` V — extraction accuracy ≥ 0.85 on 20 real syllabus transcripts
- `T50.6` I — mixed session's syllabus segment alone is routed to A6 (AC-13)
**Exit:** syllabus lectures produce structured course outlines in the dedicated store.

### S51 — Syllabus Document Upload Path
**Deps:** S50
**SRS:** FR-2.22 · §12.5
**Scope:** Accept a syllabus PDF/image/text upload, extract structure with Docling (+ OCR for scans), feed to A6, write to DB-3. **Surfaced prominently in the subject-creation flow** because §12.5 shows syllabus seeding is the highest-leverage cold-start fix — it converts unsupervised topic discovery into an easier alignment problem.
**Deliverables:** upload endpoint · Docling integration · prominent onboarding placement
**Tests:**
- `T51.1` I — PDF syllabus parsed into correct item hierarchy
- `T51.2` I — scanned/photographed syllabus handled via OCR
- `T51.3` I — malformed document fails gracefully with a user-facing message
- `T51.4` E — upload appears in the subject-creation flow, not buried in settings
- `T51.5` V — parsed items match human reading on 20 real syllabi (≥ 0.85)
**Exit:** a user can seed a subject with its syllabus before the first lecture.

### S52 — Coverage Mapping & Dashboard
**Deps:** S51, S32
**SRS:** FR-2.12, FR-6.8, FR-7.6
**Scope:** Align discovered topics to syllabus items by embedding similarity; persist `coverage_status` (`not_started` / `partial` / `covered`) and `covered_by` topic IDs. Subject dashboard showing declared vs covered vs outstanding. Alignment is advisory and user-correctable.
**Deliverables:** alignment logic · coverage persistence · dashboard · manual correction
**Tests:**
- `T52.1` V — topic-to-syllabus alignment accuracy ≥ 0.80 on labelled data
- `T52.2` I — **dashboard correctly reports taught vs outstanding items** (AC-14)
- `T52.3` I — coverage updates automatically after each session
- `T52.4` I — user correction of a wrong alignment persists and is not overwritten
- `T52.5` I — coverage query works through the FDW link (S11)
**Exit:** users can see what the course has covered and what remains.

### S53 — Syllabus-Seeded Cold Start
**Deps:** S52
**SRS:** §12.5
**Scope:** When a syllabus exists before the first lecture, **seed topic centroids from syllabus item embeddings** so session 1 clusters against a known structure instead of discovering blind. Tighter re-clustering cadence for sessions 2–5 while centroids are unstable.
**Deliverables:** centroid seeding · early-session re-cluster cadence
**Tests:**
- `T53.1` V — **first-session clustering purity with seeding materially exceeds unseeded baseline** (the core justification)
- `T53.2` I — seeded centroids are replaced by observed data as real sessions accumulate
- `T53.3` I — no-syllabus path still works (seeding is optional)
- `T53.4` I — sessions 2–5 trigger re-clustering per the tighter cadence
**Exit:** the cold-start weakness is measurably reduced when a syllabus is available.

---

# BLOCK 10 — RETRIEVAL & ASSESSMENT

### S54 — Reranker Service
**Deps:** S36
**SRS:** v2.0 §3.4 · v1.1 §15
**Scope:** Qwen3-Reranker served alongside TEI. Always-on for A3/A5 retrieval — no cost gating, per v2.0. Two-stage retrieval: vector/hybrid recall then cross-encoder rerank.
**Deliverables:** reranker service · two-stage retrieval helper
**Tests:**
- `T54.1` I — reranker returns scores for candidate sets
- `T54.2` V — **reranking improves retrieval precision@5 over first-stage-only** on a labelled query set
- `T54.3` P — reranking 50 candidates in < 500ms
- `T54.4` I — reranker unavailable → first-stage results used, pipeline continues
**Exit:** retrieval precision improved by always-on reranking.

### S55 — Shared Retrieval Service
**Deps:** S54, S48
**SRS:** FR-3.7, D-12 · ADR-012 · v2.1 §2
**Scope:** Stateless `RetrievalService` over DB-1/DB-2, called **independently** by A3 and A5. Hybrid recall → rerank → optional hierarchical merge. **Evaluate LlamaIndex's auto-merging retriever** for the utterance→segment→topic hierarchy against a hand-rolled SQL implementation (D-31); adopt whichever measures better.
**Deliverables:** RetrievalService · hierarchical merge · LlamaIndex vs hand-rolled comparison · D-31 decision
**Tests:**
- `T55.1` I — service is stateless; identical query returns identical results regardless of caller
- `T55.2` I — **service holds no agent identity and no shared state between callers** (FR-3.7 structural assertion)
- `T55.3` V — hierarchical merge returns topic-level context rather than disconnected utterances
- `T55.4` V — LlamaIndex vs hand-rolled measured on the same labelled query set; decision recorded
- `T55.5` I — retrieval scoped to a single subject
- `T55.6` P — full retrieval (recall + rerank + merge) in < 1s
**Exit:** one retrieval implementation serves both agents without coupling them.

### S56 — A3 History Context
**Deps:** S55, S38
**SRS:** FR-3.5
**Scope:** A3 identifies relationships between current session content and prior stored content by querying DB-1/DB-2 through RetrievalService (read-only). Emits typed links (`builds_on`, `revisits`, `contradicts`, `prerequisite_for`) surfaced in notes as cross-references.
**Deliverables:** A3 agent · link schema · note cross-references
**Tests:**
- `T56.1` I — A3 identifies a genuine relationship on a prepared multi-session fixture
- `T56.2` S — **A3 has read-only DB access; write attempt rejected at the database**
- `T56.3` I — **A3 makes no call to A5 and consumes no A5 output** (trace-asserted)
- `T56.4` V — human review: links judged meaningful ≥ 0.75 on 40 links
- `T56.5` I — A3 on the first session in a subject (no history) returns empty, no error
**Exit:** notes carry meaningful cross-session context.

### S57 — A5 Question Generation & Answerability Check
**Deps:** S55, S38, S36
**SRS:** FR-3.6, FR-3.7, FR-7.3, FR-7.4 · v2.0 §4.1
**Scope:** A5 generates questions, quizzes and mock tests with configurable count, difficulty and topic coverage. **Answerability check via consensus:** a *different* model attempts each question using only the stored notes; unanswerable questions are discarded. This is one of the strongest applications of the multi-model idea.
**Deliverables:** A5 agent · test configuration · answerability filter · assessment API
**Tests:**
- `T57.1` I — questions generated for requested topics at requested count
- `T57.2` I — **generated questions are answerable from the stored notes** (AC-19, enforced by the check)
- `T57.3` V — **answerability check discards a measurable fraction of bad questions** (the filter does work)
- `T57.4` S — A5 has read-only DB access
- `T57.5` I — **no A3↔A5 communication in traces** (AC-15)
- `T57.6` I — difficulty setting changes question character (human-verified on samples)
- `T57.7` P — 20-question test generated in < 30s (NFR-P5)
**Exit:** generated assessments are answerable from the user's own notes.

### S58 — Flashcards, Spaced Repetition & Export
**Deps:** S57
**SRS:** FR-7.3, FR-7.5, FR-7.7, FR-7.9
**Scope:** Flashcard generation per topic. **FSRS** scheduling over review history for adaptive difficulty (FR-7.5/7.9). Review UI. Export: Markdown, PDF via Typst, DOCX via Pandoc, and **Anki via genanki**.
**Deliverables:** flashcards · FSRS scheduler · review UI · export endpoints
**Tests:**
- `T58.1` I — flashcards generated with valid Q/A pairs
- `T58.2` U — FSRS scheduling correct against reference implementation on a known review sequence
- `T58.3` I — review results persisted and influence subsequent scheduling (FR-7.9)
- `T58.4` V — question selection weights toward poorly-performing topics (FR-7.5)
- `T58.5` I — Markdown, PDF and DOCX exports produce valid files with KaTeX/Mermaid rendered
- `T58.6` I — Anki `.apkg` imports successfully into Anki
**Exit:** study materials are generated, scheduled adaptively, and exportable.

---

# BLOCK 11 — VISUAL & MULTIMODAL

### S59 — Post-Session Upload, EXIF Strip & Dedup
**Deps:** S14, S47
**SRS:** FR-4.13, FR-4.14, FR-4.19 · NFR-S1
**Scope:** Post-session upload UI and API for board photos, handwritten notes, textbook pages, PDFs. **Strip EXIF/GPS on ingest** — a privacy requirement easily missed. pHash near-duplicate detection (FR-4.19). Upload triggers the `uploads.ready` partial re-run from S47.
**Deliverables:** upload UI/API · EXIF stripping · pHash dedup · re-run trigger
**Tests:**
- `T59.1` I — image, PDF and multi-page uploads accepted
- `T59.2` S — **GPS and all EXIF metadata absent from stored objects** (privacy assertion)
- `T59.3` I — two photos of the same board detected as near-duplicates and merged
- `T59.4` I — upload after notes exist triggers the partial re-run, not a full reprocess
- `T59.5` I — oversized/unsupported file rejected with a clear message
**Exit:** users upload media post-session; privacy metadata removed; duplicates handled.

### S60 — OCR Services & Confidence
**Deps:** S59, S02
**SRS:** FR-4.15, FR-4.16, FR-4.18 · ADR-008
**Scope:** PaddleOCR-VL for printed/PDF; a VLM-OCR (benchmarked at this stage) for handwriting/boards; dots.ocr fallback. OpenCV/Pillow preprocessing — deskew, perspective correct, de-glare — **before** OCR, which measurably improves handwriting accuracy. Confidence recorded; low-confidence flagged, never silently trusted. **Two-model OCR disagreement as an additional confidence signal.**
**Deliverables:** OCR services · image preprocessing · confidence scoring · disagreement signal
**Tests:**
- `T60.1` V — printed-page OCR accuracy > 0.95 on a test set
- `T60.2` V — board-photo OCR accuracy measured and **published honestly as best-effort** (SRS R-08 — no inflated claim)
- `T60.3` I — low-confidence extraction flagged, not presented as authoritative
- `T60.4` V — preprocessing measurably improves accuracy versus raw input
- `T60.5` I — **the uploaded image is retained in notes regardless of OCR success** (a user can read their own board photo even when OCR cannot)
- `T60.6` I — OCR model disagreement raises the low-confidence flag
**Exit:** uploaded media contributes text where it can, and its image where it cannot.

### S61 — Concept Detection & Text-Diagram-First Path
**Deps:** S44
**SRS:** FR-4.1 · **D-25** · v1.1 §20
**Scope:** Detect transcript concepts warranting a visual (board references, spatial/structural descriptions, named diagrams, processes). **Then attempt text-representable diagrams first** — Mermaid for flows/trees/state machines, Graphviz/D2 for graphs, Excalidraw-style for hand-drawn aesthetic, KaTeX for formulas. Only genuinely pictorial concepts (anatomy, apparatus, geography) proceed to retrieval or generation.
**Deliverables:** concept detector · text-diagram generator · routing to image path only when necessary
**Tests:**
- `T61.1` V — concept detection precision > 0.75 on labelled transcripts
- `T61.2` I — a described flowchart produces **valid Mermaid**, not an image request
- `T61.3` I — a described hierarchy produces a valid tree diagram
- `T61.4` V — **the proportion of concepts resolved by text diagrams is measured** (validates D-25's premise)
- `T61.5` I — a genuinely pictorial concept correctly routes to the image path
- `T61.6` I — all generated diagram syntax renders without error client-side
**Exit:** text-representable diagrams are produced deterministically, reducing reliance on image retrieval and generation.

### S62 — Licensed Image Retrieval & Scoring
**Deps:** S61
**SRS:** FR-4.1–4.7 · ADR-009
**Scope:** Query **only licence-filtered sources** — Openverse, Wikimedia Commons, NASA/NIH/PMC/USGS, Open Clipart. General web image search is not used, because open-web licence metadata cannot be reliably screened. Composite concept-match score per §9.4 (0.5·text-similarity + 0.5·CLIP alignment), accept at ≥ 0.50. Source and licence recorded and displayed.
**Deliverables:** source clients · composite scorer · licence capture · attribution display
**Tests:**
- `T62.1` I — retrieval returns only openly-licensed results
- `T62.2` I — **every used image has non-null `source_url` and `licence`** (enforced by the S10 constraint)
- `T62.3` V — precision@1 > 0.70 on 200 labelled concept/image pairs (§12.4)
- `T62.4` I — score below threshold routes to generation
- `T62.5` E — attribution and licence visible in the client alongside every web image (NFR-S7)
- `T62.6` I — **no general web image search endpoint exists in the codebase** (asserted by code search)
**Exit:** only licensed images are used, always attributed.

### S63 ⛔ — Image Generation & FR-4.9 Boundary (HARD GATE)
**Deps:** S62
**SRS:** FR-4.8, FR-4.9, FR-4.10 · ADR-009 · R-06
**Scope:** FLUX.1-schnell via `diffusers` in our own service. **The generation service's API accepts no image parameter whatsoever** — a restricted image cannot reach the generator because there is no field to pass it in. Generation is driven solely by textual concept description. Outputs labelled AI-generated and cached per `(subject, concept)`. Custom Semgrep rule in CI enforcing the boundary.
**Deliverables:** generation service (text-input-only API) · AI-generated labelling · concept cache · **Semgrep boundary rule**
**Tests:**
- `T63.1` S — **GATE: the generation service API has no image input parameter** (schema assertion)
- `T63.2` S — **GATE: a restricted candidate image is never persisted, cached, or passed to the generator** (AC-16, traced end to end)
- `T63.3` S — **GATE: the Semgrep rule fails CI when a code change creates any path from retrieval bytes to the generator**
- `T63.4` I — no similarity score is computed for a restricted candidate (FR-4.3 ordering: licence check precedes scoring)
- `T63.5` I — every generated image labelled AI-generated (AC-17, FR-4.10)
- `T63.6` I — repeated concept served from cache, not regenerated (FR-4.11)
- `T63.7` M — generated illustrations judged useful and stylistically consistent within a subject (D-08)
- `T63.8` I — user rejection of a generated image triggers regeneration or removal (FR-4.12)
**Exit:** **T63.1, T63.2 and T63.3 pass.** The copyright boundary is enforced structurally and by CI, not by policy or prompt wording.

### S64 — Visual Assembly into Notes
**Deps:** S63, S60
**SRS:** FR-4.16, FR-4.17
**Scope:** Attach text diagrams, licensed images, generated illustrations and OCR'd uploads to the correct note sections. Board photos matched to segments by timestamp proximity or semantic similarity (FR-4.17). Assembled into the client note view.
**Deliverables:** asset-to-section attachment · timestamp/semantic matching · client rendering
**Tests:**
- `T64.1` I — **an uploaded board photo appears in the correct topic section** (AC-18)
- `T64.2` V — timestamp/semantic matching accuracy > 0.80 on labelled uploads
- `T64.3` I — OCR'd text incorporated into note content and searchable via S48
- `T64.4` E — all asset types render correctly in the client
- `T64.5` I — a section with no assets renders cleanly (no empty placeholders)
**Exit:** visual material lands in the right place in the notes.

---

# BLOCK 12 — FINE-TUNING & THE DATA FLYWHEEL

### S65 — Correction Capture & Training Data Pipeline
**Deps:** S49
**SRS:** FR-2.11, FR-4.12 · v2.0 §6.2
**Scope:** Turn every human correction into labelled training data. Capture points: A1 relevance overrides (user marks a filtered utterance as wanted, or vice versa), topic label edits (S31), topic/partition split-merge corrections, syllabus alignment corrections (S52), image rejections (S63), and note edits. All written to a `corrections` table with the original prediction, the human value, and enough context to reconstruct the training example. Export flow producing versioned datasets in DVC.
**Deliverables:** `corrections` schema · capture hooks at all six points · dataset export flow · DVC integration
**Tests:**
- `T65.1` I — each of the six correction types is captured with original prediction, corrected value and context
- `T65.2` I — corrections are immutable and append-only (an audit trail, not editable state)
- `T65.3` I — export produces a training-ready dataset with no PII and no cross-user leakage
- `T65.4` U — export is DVC-reproducible and versioned
- `T65.5` I — a correction immediately affects the user's view (it is a real product feature, not just telemetry)
- `T65.6` S — corrections from one user never appear in another user's training export without explicit consent flag
**Exit:** every human correction becomes both an immediate product improvement and a durable training example.

### S66 — A1 Classifier Distillation
**Deps:** S65, S42
**SRS:** v2.0 §6.1 (priority 1)
**Scope:** Distil the large model's relevance judgments into a small dedicated classifier. Generate ~5k labels with the primary LLM, validate against the 2k human-labelled set from S05 plus S65 corrections, then fine-tune a small encoder (setfit or a 0.5B classifier) via Unsloth/PEFT. Target: match large-model accuracy at far higher throughput, potentially CPU-servable.
**Deliverables:** distillation dataset · fine-tuned classifier · serving integration · A/B comparison
**Tests:**
- `T66.1` V — **distilled classifier precision on discard within 2 points of the large model** on the S42 held-out set
- `T66.2` V — **recall within 3 points of the large model**
- `T66.3` P — throughput at least 20× the large model per utterance
- `T66.4` V — **zero core-content utterances discarded** (the S42 T42.4 assertion must still hold)
- `T66.5` I — classifier swapped in by config; large model remains available as fallback
- `T66.6` V — A/B on live sessions shows no quality regression in resulting notes
**Exit:** A1 runs at a fraction of the cost and latency with no measurable quality loss.

### S67 — Embedding Contrastive Fine-Tune
**Deps:** S65, S30, S32
**SRS:** v2.0 §6.1 (priority 2) · v2.1 §3.1
**Scope:** Contrastively fine-tune the embedding model on accumulated lecture data: same-topic utterance pairs as positives, cross-topic as negatives. **Hard negatives mined with faiss-gpu** over the full corpus — nearest neighbours that are confirmed different-topic. Trained with sentence-transformers v3. New model version stamped; rollout via the S25 per-subject resumable backfill.
**Deliverables:** hard-negative mining pipeline · contrastive training run · new model version · staged backfill
**Tests:**
- `T67.1` V — **clustering purity improves over the Qwen3 baseline** on S05 labels (the point of the exercise)
- `T67.2` V — cross-session topic matching accuracy (S32 T32.1) improves
- `T67.3` V — retrieval precision@5 (S55) improves or holds
- `T67.4` I — hard-negative mining returns confirmed different-topic neighbours, not mislabelled positives
- `T67.5` I — backfill migrates one subject at a time, resumably; both versions coexist safely during rollout
- `T67.6` I — rollback to the prior version possible without data loss
- `T67.7` V — no regression on any subject (per-subject before/after comparison)
**Exit:** the embedding model is domain-adapted, with a safe staged rollout and rollback path.

### S68 — ASR Domain Adaptation
**Deps:** S65, S05, S06
**SRS:** v2.0 §6.1 (priority 3) · attacks R-01/SR-01 at the root
**Scope:** Fine-tune the selected ASR model on 10–20h of transcribed local audio — your lecturers, your rooms, your subject vocabulary, your accents. This addresses the project's critical-path risk at its source rather than mitigating downstream. Evaluate per-condition to confirm improvement is broad, not overfitted to one room.
**Deliverables:** training set · fine-tuned ASR model · per-condition evaluation · serving swap
**Tests:**
- `T68.1` V — **WER improves over the S06 baseline on held-out local audio**
- `T68.2` V — improvement holds across **all** S04 conditions (not just the best-represented one)
- `T68.3` V — no regression on general-domain audio (guards against catastrophic forgetting)
- `T68.4` V — technical-vocabulary recognition specifically improved (subject-term test set)
- `T68.5` V — hallucination rate (S22 metric) not increased by fine-tuning
- `T68.6` I — model swapped in by config; base model retained as fallback
**Exit:** ASR is adapted to the actual deployment environment with measured, broad improvement.

### S69 — Multi-LoRA Serving & Adapter Registry
**Deps:** S66, S36
**SRS:** v2.0 §6.3
**Scope:** vLLM multi-LoRA so one base model in VRAM serves several agent-specific adapters — A2 note style, A5 question generation, A6 syllabus extraction — routed per agent with no model reload. Adapter registry in `config/models.yaml` with version pinning. LoRA training for A2 style (from S65 note edits) and A6 extraction.
**Deliverables:** multi-LoRA serving config · adapter registry · A2 style LoRA · A6 extraction LoRA
**Tests:**
- `T69.1` I — multiple adapters served concurrently from one base model
- `T69.2` I — agent-to-adapter routing correct; each agent receives its own adapter
- `T69.3` P — adapter swap adds negligible latency versus base-model inference
- `T69.4` V — A2 style LoRA produces notes rated closer to human-preferred examples than base (S44 T44.4 rubric)
- `T69.5` V — A6 extraction LoRA improves syllabus extraction accuracy over S50 baseline
- `T69.6` I — adapter version recorded on every `agent_runs` row
- `T69.7` I — a failed adapter load falls back to the base model rather than failing the request
**Exit:** specialised per-agent models are served from a single base model load.

---

# BLOCK 13 — HARDENING & FULL ACCEPTANCE

### S70 — Observability Stack
**Deps:** S49
**SRS:** NFR-P*, NFR-C1 · v1.1 §22
**Scope:** Deploy the consolidated stack — SigNoz (or Prometheus + Grafana + Loki + Tempo), plus dcgm-exporter, postgres-exporter, node-exporter, cAdvisor, GlitchTip, Uptime Kuma, Alertmanager routing to n8n. Build the **seven dashboards** identified in v1.1 §22: sessions funnel, WER proxy (mean ASR confidence trended), cost per session by agent, A1 efficiency, topic health per subject, GPU utilisation and queue depth, vector query P95.
**Deliverables:** observability deployment · exporters · seven dashboards · alert rules
**Tests:**
- `T70.1` I — all seven dashboards render with live data
- `T70.2` I — GPU metrics present and accurate against `nvidia-smi`
- `T70.3` I — a deliberately failed session fires an alert reaching n8n within 2 minutes
- `T70.4` I — **the WER-proxy dashboard detects an injected audio-quality regression** (the dashboard has diagnostic value, not just decoration)
- `T70.5` I — per-session cost queryable and matching `agent_runs` sums
- `T70.6` I — trace spans correlate across API → Prefect → LangGraph → model service
**Exit:** system health, cost and quality are observable, with alerts that fire on real conditions.

### S71 — Backup, DR & Restore Drill
**Deps:** S49
**SRS:** NFR-R8
**Scope:** pgBackRest on both PG instances (daily full, 15-minute WAL archiving, 30-day retention). restic for MinIO bucket contents. Healthchecks.io dead-man's-switch alerting when a backup *doesn't* run. **A documented and actually-executed restore drill** — a backup never tested is not a backup.
**Deliverables:** backup configuration both instances · restic schedule · heartbeat monitoring · restore runbook · drill record
**Tests:**
- `T71.1` I — full backup completes and is verifiable on both PG-MAIN and PG-SYLLABUS
- `T71.2` I — WAL archiving active; PITR to an arbitrary timestamp succeeds
- `T71.3` E — **full restore to a clean host reproduces a working system with all data intact** (the actual drill)
- `T71.4` I — a suppressed backup triggers the dead-man's-switch alert
- `T71.5` I — object-store restore recovers audio, uploads and generated images
- `T71.6` M — restore runbook followed successfully by someone who did not write it
**Exit:** a verified, drilled restore path exists for both databases and the object store.

### S72 — Auth, IdP & Multi-User
**Deps:** S49, S12
**SRS:** NFR-S2, NFR-S6, D-13
**Scope:** Replace the S12 auth stub with Authentik (OIDC). Multi-user tenancy verified against the existing RLS policies. Implement full data export and account deletion with cascade across DB-1, DB-2, DB-3, object store and metadata (NFR-S6).
**Deliverables:** Authentik deployment · OIDC integration · export endpoint · deletion cascade
**Tests:**
- `T72.1` E — OIDC login, logout and token refresh work
- `T72.2` I — RLS holds under the new auth (re-run S12 T12.1/T12.2)
- `T72.3` I — **account deletion removes all data across all three databases and the object store** (AC-20)
- `T72.4` I — data export produces a complete, readable archive of the user's own data only
- `T72.5` S — deletion verified by direct database and bucket inspection, not just API response
- `T72.6` I — 20 concurrent users isolated correctly under load
**Exit:** multi-user deployment with verified isolation, export and deletion.

### S73 — Performance Tuning to NFR Targets
**Deps:** S70
**SRS:** NFR-P1 … NFR-P7
**Scope:** Measure and tune against every NFR-P target. HNSW parameter tuning (`m`, `ef_construction`, `ef_search`) per partition using HypoPG/pg_qualstats. PgBouncer pool sizing. Prefect concurrency limits. Locust load test at 20 concurrent sessions. **Evaluate VectorChord** specifically for re-embed insert throughput (D-27).
**Deliverables:** performance report vs all targets · tuned index parameters · load test suite · D-27 decision
**Tests:**
- `T73.1` P — NFR-P1: ASR real-time factor < 1.0
- `T73.2` P — NFR-P2: topic window result ≤ 60s after the 10-minute mark
- `T73.3` P — NFR-P3: post-session processing ≤ 15 min P90 for a 60-minute lecture
- `T73.4` P — NFR-P4: consolidated note retrieval < 3s P95
- `T73.5` P — NFR-P5: 20-question test < 30s P90
- `T73.6` P — NFR-P6: vector search < 200ms P95
- `T73.7` P — **NFR-P7: ≥ 20 concurrent live sessions sustained** on one node
- `T73.8` P — VectorChord vs pgvector insert throughput measured on a full-subject re-embed
**Exit:** every NFR-P target met and recorded, with the measurement suite repeatable in CI.

### S74 — GPU Scheduling & Training Isolation
**Deps:** S69, S73
**SRS:** v2.0 §8 · v2.1 §5.3
**Scope:** Prevent training runs from starving live serving. MIG partitioning on A100/H100-class hardware, otherwise scheduled training windows plus hard GPU-affinity assignment in the job queue. KEDA (or equivalent) scaling the image-generation and OCR workers to zero between sessions. Ray Serve if multiplexing across multiple hosts.
**Deliverables:** GPU scheduling policy · MIG or window configuration · scale-to-zero for bursty services
**Tests:**
- `T74.1` I — **a fine-tuning job running concurrently does not degrade live ASR latency beyond NFR-P1**
- `T74.2` I — image-gen worker scales to zero when idle and wakes on demand within an acceptable cold-start
- `T74.3` I — a training job cannot claim GPU memory reserved for serving
- `T74.4` I — service start order enforced after a full host reboot (S36 T36.2 regression)
- `T74.5` P — GPU utilisation during idle periods drops measurably (cost/power validation)
**Exit:** training and serving coexist without contention.

### S75 — Corpus Reprocessing & Re-Clustering Operations
**Deps:** S74
**SRS:** FR-5.12, FR-5.13 · v2.0 §3.5
**Scope:** Scheduled overnight job reprocessing stored sessions with current models and prompts, so existing notes improve retroactively — economically viable only on owned GPUs. Operator tooling for full subject re-cluster, and partition **merge/split** with audit logging (FR-5.13). Embedding-version backfill promoted to a first-class operation.
**Deliverables:** reprocessing flow · re-cluster operator tooling · merge/split with audit log · backfill runbook
**Tests:**
- `T75.1` I — reprocessing a session with a newer prompt version produces updated notes without duplication
- `T75.2` I — **reprocessing preserves user edits and corrections** (S65 data is not overwritten)
- `T75.3` I — full subject re-cluster preserves user-edited topic labels (S31 T31.3 regression)
- `T75.4` I — partition merge and split both recorded in the audit log with before/after state
- `T75.5` I — a merge can be reversed from the audit record
- `T75.6` P — overnight reprocessing of 100 sessions completes within the window
- `T75.7` V — reprocessed notes rated equal or better than originals (human sample)
**Exit:** the corpus improves as the system improves, without losing human contributions.

### S76 ⛔ — Security, Licence & Full System Acceptance (FINAL GATE)
**Deps:** S70–S75, all blocks
**SRS:** AC-1 … AC-20 · §15 · v1.1 §30
**Scope:** Full acceptance run. Trivy/Grype image scanning, Semgrep/Bandit SAST, gitleaks history scan, OWASP-style review of the API surface. Automated licence audit via `pip-licenses` + `syft` SBOM against the 22-item licence register in v1.1 §30, with the n8n (D-14), MinIO (D-23) and remaining flags resolved. Legal review of recording consent (§15.1) confirmed complete before any release beyond pilot.
**Deliverables:** security report · SBOM per image · licence audit · resolved licence decisions · legal sign-off record · full AC suite green
**Tests:**
- `T76.1` E — **AC-1 … AC-20 all pass** against the full deployment
- `T76.2` S — no critical or high CVEs unresolved in any shipped image
- `T76.3` S — SAST clean; the FR-4.9 Semgrep boundary rule present and passing (S63 T63.3 regression)
- `T76.4` S — **licence audit clean against the §30 register; every flagged component resolved or consciously accepted with a recorded decision**
- `T76.5` S — SBOM generated and stored per image
- `T76.6` S — no secrets in git history
- `T76.7` S — **NFR-S4 re-verified: no voiceprint or biometric data anywhere in the system** (S20 T20.2 regression)
- `T76.8` M — consent and recording-legality legal review documented and signed off (D-11)
- `T76.9` S — penetration test of the API surface with findings triaged
- `T76.10` M — restore drill (S71) re-executed successfully post-hardening
**Exit:** **All twenty AC tests pass, security and licence audits are clean, and legal sign-off is recorded.** The system is releasable.

---

# APPENDICES

## A. Gate Summary

| Gate | Stage | Condition | If it fails |
|---|---|---|---|
| **G1** | S06 | ASR WER < 20%; clustering purity > 0.60 | **Halt.** Fix audio capture (mic, placement, room) before any further stage. Nothing downstream can exceed transcript quality. |
| **G2** | S20 | End-to-end capture → durable transcript | Fix ingestion before building intelligence on top of it |
| **G3** | S29 | Segmentation P_k < 0.30 **and** beats baselines | Revise segmentation before clustering inherits its error |
| **G4** | S42 | A1 discard precision > 0.90; **zero core content discarded** | Recalibrate or revise A1 before notes are built from its output |
| **G5** | S49 | AC-1…AC-11 pass; pilot feedback positive | **MVP decision point.** Reassess scope before committing to Blocks 9–13 |
| **G6** | S63 | Generation API has no image input; Semgrep rule enforces it | Do not ship image generation until the boundary is structural |
| **G7** | S76 | AC-1…AC-20, security, licence, legal | Not releasable |

## B. Critical Path

```
S01→S02→S03→S04→S05→[G1 S06]→S07→S08→S09→S13
   →S14→S15→S16→S17→S19→[G2 S20]→S21→S22→S23
   →S25→S26→S27→S28→[G3 S29]→S30→S31→S32
   →S36→S37→S38→S41→[G4 S42]→S44→S45→S46→S47→[G5 S49]
```

**Parallelisable off the critical path:** S10/S11/S12 (alongside S09); S18/S24 (alongside S21–S23); S33/S34/S35 (alongside S36–S40); S39/S40 (alongside S41); S48 (alongside S47); all of Blocks 9–12 after G5.

## C. Traceability — SRS Requirement to Stage

| SRS block | Stages |
|---|---|
| FR-1 (audio) | S15, S16, S17, S18, S19, S20 |
| FR-2 (transcript/topic/filter) | S19, S21–S24, S26, S28–S35, S41–S43, S50, S51 |
| FR-3 (agents) | S36–S43, S44, S50, S56, S57 |
| FR-4 (visual) | S59–S64 |
| FR-5 (storage/routing) | S08–S11, S25, S27, S30, S32, S45, S47, S75 |
| FR-6 (subject layer) | S07, S08, S12, S52 |
| FR-7 (outputs) | S24, S46, S48, S52, S57, S58 |
| NFR-P (performance) | S73 |
| NFR-R (reliability) | S23, S27, S37, S47, S71 |
| NFR-S (security/privacy) | S12, S14, S20, S59, S72, S76 |
| NFR-C (cost) | S39, S66, S70 |
| AC-1…AC-11 | S49 |
| AC-12…AC-20 | S76 |
| v2.0 GPU revisions | S21, S36, S43, S44, S65–S69, S74, S75 |
| v2.1 additions | S02, S48, S55, S61 |

## D. Stage Count by Block

| Block | Stages | Count | Est. duration |
|---|---|---|---|
| B0 Foundation | S01–S06 | 6 | 2–3 wk (S06 is 2–4 days) |
| B1 Data foundation | S07–S13 | 7 | 3 wk |
| B2 Ingestion | S14–S20 | 7 | 3–4 wk |
| B3 Transcript integrity | S21–S24 | 4 | 2 wk |
| B4 Topic intelligence | S25–S32 | 8 | 3 wk |
| B5 Window & routing | S33–S35 | 3 | 1–2 wk |
| B6 LLM infrastructure | S36–S40 | 5 | 2 wk |
| B7 Core agents | S41–S46 | 6 | 3 wk |
| B8 MVP close | S47–S49 | 3 | 2 wk + 2 wk pilot |
| B9 Syllabus | S50–S53 | 4 | 2–3 wk |
| B10 Assessment | S54–S58 | 5 | 2–3 wk |
| B11 Visual | S59–S64 | 6 | 3 wk |
| B12 Fine-tuning | S65–S69 | 5 | 3–4 wk |
| B13 Hardening | S70–S76 | 7 | 4 wk |
| **Total** | **S01–S76** | **76** | **~9–11 months** |

**MVP (through S49): ~5 months.** Blocks 9–13 are additive and independently sequenceable after the G5 decision point.

## E. Test Inventory

| Type | Count (approx) | Where they run |
|---|---|---|
| `U` unit | ~70 | every PR |
| `I` integration | ~150 | `main` merge, testcontainers |
| `E` end-to-end | ~30 | nightly + pre-gate |
| `V` eval/metric | ~65 | nightly eval suite, gate stages |
| `M` manual/human | ~20 | gate stages only |
| `P` performance | ~30 | weekly + S73 |
| `S` security/licence | ~30 | every PR (fast) + S76 (full) |
| **Total** | **~395** | |

**Rule:** a stage does not close until its own tests pass **and** all prior regression assertions still pass. Seven tests are explicitly marked as regression anchors to be re-run at S76: T20.2 (no voiceprints), T36.2 (VRAM start order), T42.4 (no core content discarded), T31.3 (label preservation), T63.3 (FR-4.9 Semgrep), T12.1/T12.2 (RLS isolation).

## F. Per-Stage Spec Document Template

Each stage expands into a specification document with these sections:

```
1. Stage identity        ID, name, block, owner, estimate
2. Context               why this stage exists; what precedes it
3. Dependencies          upstream stages, external services, model versions
4. Requirements traced   SRS/ADR IDs implemented, verbatim
5. Interface contracts   SQL DDL · Pydantic schemas · API paths and payloads
                         · prompt text and version · event names
6. Implementation notes  algorithm detail, config keys, failure handling
7. Test specification    each T##.n expanded to given/when/then with fixtures
8. Observability         metrics/spans/log events added by this stage
9. Rollback              how to revert; migration down-path; feature flag
10. Exit checklist       the closing condition, signed off
```

---

*Master Implementation Plan v1.0 — 76 stages, 14 blocks, 7 gates, ~395 tests. Per-stage specifications to be generated from §F. G1 (S06) must pass before S07 begins.*

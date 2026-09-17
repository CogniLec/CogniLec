# How the system works: pipeline stage by stage

Companion to `docs/about.md`. This explains what each major piece of the
system actually does, in the order data flows through it, and which file
owns each responsibility. Read `docs/about.md` first for orientation.

## 1. Audio capture (client-side)

- `src/client/src/services/Recorder.ts` — wraps the browser's
  `MediaRecorder` API, emits fixed-length audio chunks (not one giant
  file) as the user records, so upload can start before recording ends.
  Sets `isFinal: true` on the chunk emitted when `.stop()` is called.
- `src/client/src/services/UploadQueue.ts` — queues chunks and uploads
  them one at a time via `src/client/src/services/api.ts`'s
  `uploadSessionChunk()`, retrying on failure. Chunks are buffered in
  IndexedDB (`src/client/src/services/db.ts`) so a page reload/crash
  mid-recording doesn't lose already-captured audio.
- `src/client/src/hooks/useRecorder.ts` — ties the above together, calling
  `POST /api/v1/sessions/` to create a real backend session before
  recording starts (not a client-side-only UUID).

## 2. Chunk ingestion (backend, real-time path)

- `POST /api/v1/sessions/{id}/chunks` (`src/api/routes/chunks.py`) — each
  chunk is a multipart upload; `src/services/chunk_ingestion.py` stores the
  raw audio in MinIO (bucket `lis-audio`, key
  `{session_id}/chunks/{seq}.opus`) and publishes a message onto the
  `audio.chunk` Valkey Stream (consumer group pattern, not pub/sub — so a
  worker restart doesn't lose in-flight chunks).
- This is deliberately the *only* real-time-latency-sensitive part of the
  whole system (ADR-014's "Phase 1: Live" vs "Phase 2: Post-Session"
  split) — once a chunk is durably in MinIO + the stream, nothing else has
  to happen synchronously with the recording.

## 3. Preprocessing (`src/workers/preprocessing_worker.py`)

Consumes `audio.chunk`, runs each chunk through resampling, loudness
normalization, and VAD (voice-activity detection) to strip silence, writes
the processed WAV to MinIO, and publishes `audio.processed`. Carries the
`is_final` flag through from the original chunk message — this is the flag
that eventually tells the ASR worker a recording is actually complete.

## 4. Transcription (`src/workers/asr_worker.py`)

Consumes `audio.processed`, runs faster-whisper (currently
`deepdml/faster-whisper-large-v3-turbo-ct2`, CPU-forced on this image —
see `docs/gaps.md` for why) over each chunk, persists one row per
recognized phrase into the partitioned `utterances` table (subject_id,
session_id, seq, start_ms, end_ms, text, per-word confidence). On the
chunk marked `is_final`, transitions the session to `TRANSCRIBED` and —
critically — **auto-triggers everything below** via
`src/services/orchestration/auto_study_materials.py`. No manual "generate
notes" step exists in the real flow.

## 5. The post-transcription pipeline (T1-T7 + T3b)

All defined in `src/services/orchestration/session_pipeline.py` as a
single Prefect flow (`process_session`), run automatically once
transcription finishes:

- **T1 embed_utterances** — embeds each utterance (TEI primary, local
  `sentence-transformers` CPU fallback if TEI is unreachable) into a
  1024-dim vector (`Qwen/Qwen3-Embedding-0.6B`), stored per-utterance.
- **T2 segment_session** — TextTiling-style boundary detection over the
  embedding sequence to split the session into topic-coherent segments.
- **T3 cluster_segments** — BERTopic-style clustering of segments into
  `Topic` rows (a topic can span multiple sessions of the same subject —
  cross-session topic identity, ADR-010).
- **T3b label_topics** — generates a real, human-readable label + keywords
  for each new topic (LLM call + c-TF-IDF/KeyBERT). Added 2026-09-17;
  without this, flashcard generation retrieves against a meaningless
  placeholder and hallucinates ungrounded content (see gap #33b).
- **T4 route_session_type** — dispatches `content` sessions into T5-T7;
  `syllabus`/`mixed` sessions route elsewhere (A6, out of scope here).
- **T5 filter_utterances** (agent A1) — classifies each utterance
  on-topic/off-topic against its segment's topic label, in batches (LLM
  call per batch, `guided_json`-constrained for reliability). Soft-delete
  only (`is_relevant` flag, never a row deletion).
- **T6 synthesize_notes** (agent A2) — one LLM call over the *entire*
  relevant transcript (not batched, for cross-section coherence), produces
  structured note sections with citations back to specific utterance IDs.
- **T7 persist_notes** — idempotent upsert of note sections, flips
  `notes_ready` on the session.

## 6. Flashcard generation (`auto_study_materials.py`, after T7)

For each topic with persisted notes, `FlashcardGenerator`
(`src/services/study/flashcards.py`) retrieves relevant content (hybrid
search + reranking, `src/services/retrieval/`) and generates 5 Q/A
flashcards per topic via another LLM call, persisted with initial FSRS
(spaced-repetition) scheduling fields
(`src/services/study/fsrs_scheduler.py`).

## 7. Study/review (frontend + `src/api/routes/study.py`)

`GET /flashcards/next` returns the next due card (FSRS-ordered);
`POST /flashcards/{id}/review` records a self-graded review (Again/Hard/
Good/Easy) and reschedules the card. `src/client/src/components/QuizCard.tsx`
is the UI for this.

## Data storage layout

- **Postgres** (`lis-pg-main`, pgvector extension) — everything structured:
  `subjects`, `sessions`, `utterances`/`segments`/`note_sections`/
  `note_provenance` (all partitioned by `subject_id` — see the partition
  gotcha in `docs/about.md`), `topics`, `flashcards`, `corrections`. Row-
  Level Security enforces per-user isolation on the 6 tables it's applied
  to (`lis_app` role, non-superuser — see ADR-013 / gap #4).
- **MinIO** (S3-compatible) — raw + preprocessed audio (`lis-audio`
  bucket), user-uploaded materials (`lis-uploads`), generated exports
  (`lis-exports`/`lis-generated`).
- **Valkey** — the real-time stream backbone (`audio.chunk`,
  `audio.processed` Streams with consumer groups) plus pub/sub for live
  status events the frontend can subscribe to.

## LLM access (`src/services/llm/router.py` + `config/litellm.yaml`)

All LLM calls go through one `LLMRouter.complete()` call site per agent,
which talks to a LiteLLM proxy (not vLLM directly) as its Tier-1 backend.
LiteLLM's own `model_list` can have multiple entries sharing one
`model_name` for load-balanced throughput across separate GPUs (added
2026-09-17 — see gap #33c) — this is the mechanism to add more LLM
capacity, not more in-process `asyncio` concurrency against one GPU (that
was tried and made things worse on a single card, gap #33b).

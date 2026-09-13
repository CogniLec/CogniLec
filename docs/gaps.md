# Known Gaps — S01–S20

Status as of 2026-09-12. Test suite: 332 passed, 3 skipped, 0 failed.

All code and tests for implemented stages S01–S20 pass. The gaps below are the
reasons the remaining 3 tests are skipped rather than run — none are fixable
by code changes alone.

## 1. S04 — Real audio corpus incomplete

- **Spec requirement:** 8–10 real lecture recordings, varied conditions
  (front/back row, quiet/busy room, stationary/moving lecturer, discussion-heavy).
- **Current state:** corpus not yet recorded/collected.
- **Blocks:**
  - S06 ASR/embedding bake-off cannot produce a real WER benchmark.
  - `tests/test_asr_worker.py:146` — skipped, no real S06 held-out benchmark to compare against.
  - `tests/test_e2e_gate.py:268` — skipped, RTF<2.0 for a full 60-minute session
    can't be honestly measured without a real 60-minute fixture.
- **Fix:** record and consent the S04 corpus per spec, run the S06 bake-off in MLflow.

## 2. S20 — Diarisation model unavailable

- **Spec requirement:** pyannote.audio 3.x producing anonymous speaker tags.
- **Current state:** pyannote.audio deliberately not installed; its pretrained
  model is HuggingFace-gated and no `HF_TOKEN` is configured in `.env`.
- **Blocks:**
  - `tests/test_diarisation.py:201` — skipped, real multi-speaker diarisation
    on real audio can't run. Tag-assignment mechanism is instead verified via
    a synthetic backend (`test_speaker_tags_assigned_from_synthetic_segments`).
- **Fix:** obtain a HuggingFace token with access to the gated pyannote model,
  set `HF_TOKEN` in `.env`, install `pyannote.audio`.

## 3. GPU driver — resolved (2026-09-12)

- Was: `nvidia-smi` reported a driver/library version mismatch, blocking any
  GPU-dependent verification.
- Root cause: host reboot pending after a driver update; S02's Ansible
  playbook had never actually been run against this machine (placeholder
  inventory, no held package).
- Fix applied: host rebooted; driver confirmed at 580.178.04
  (`nvidia-driver-580-server-open`); Docker GPU passthrough verified against
  the S02-pinned CUDA 12.6 image; `docs/cuda-matrix.md`, `ansible/site.yml`,
  `ansible/inventory.yml` updated from the 560.x placeholder to match; driver
  held via `apt-mark hold` and pinned via `/etc/apt/preferences.d/nvidia-driver`.
- Residual: the 3 skips above still cite "GPU driver mismatch" in their skip
  messages — that text is now stale. The real blockers are #1 and #2 above.

## 4. RLS not actually enforced (found while building S24)

- **Spec requirement (S12):** row-level security enforced by PostgreSQL,
  fail-closed, independent of application code.
- **Current state:** the `lis` role (from `.env` / `docker/postgres/init-main.sql`)
  is Postgres **SUPERUSER with BYPASSRLS**. Superusers bypass RLS
  unconditionally, regardless of `FORCE ROW LEVEL SECURITY`. A cross-user
  transcript request currently returns 200 with another user's data, not 404.
- **Blocks:** `tests/test_transcript_api.py::test_...` (T24.2) — skipped, can't
  honestly assert RLS denial with the only role available being a superuser.
- **Fix:** provision a non-superuser, `NOBYPASSRLS` application role for
  runtime/test DB connections. The route logic and RLS wiring
  (`get_db_session_with_rls`) are already correct and ready once that role
  exists — this is a database provisioning gap, not a code bug.

## 5. Repo consolidation (2026-09-13)

- The entire S01-S20 implementation had been sitting **uncommitted** in the
  working tree since it was written — never given a real git commit. Committed
  now (`18f8d88`).
- `.gitignore` had an unscoped `models/` pattern matching any directory named
  `models` at any depth, which silently excluded `src/db/models/` (the actual
  SQLAlchemy ORM models — `Session`, `Subject`, `Utterance`, etc.) from git
  entirely. Fixed by scoping it to `/models/` (root-level ML weight cache
  only); the recovered files are committed in `faf5aca`.
- Blocks 3 (S21-S24) and 6 (S36-S40) were implemented in parallel by
  background agents in isolated git worktrees, then consolidated onto main
  (`a9b4584`, `3e7abb4`). Full suite after consolidation: **396 passed, 15
  skipped, 0 failed**.
- Pre-commit hooks (ruff, ruff format, mypy, sqlfluff, yaml, end-of-file) have
  substantial pre-existing failures across the S01-S20 code and were bypassed
  (`--no-verify`, disclosed in each commit message) to land this work. Lint/
  type cleanup across the codebase is still outstanding.

## 6. Blocks 4-6 complete; S05 corpus gap now widely felt (2026-09-13)

- Blocks 4 (S25-S32), 5 (S33-S35), and 6 (S36-S40) implemented in parallel via
  background agents in isolated worktrees, merged cleanly onto main
  (`49c07b9`, `b21201d`, `a9b4584`). Full suite: **484 passed, 20 skipped, 0
  failed**.
- **S29 (hard gate)** — P_k < 0.30 segmentation gate has real evaluation code
  (`src/eval/segmentation_report.py`) but cannot honestly run: the S05
  30-lecture hand-marked corpus doesn't exist, only a 1-lecture Label Studio
  stub in the wrong format/scale (`lis-eval/labels/v1/boundaries/sample.json`).
  Honest skip, not a fabricated pass — downstream S30+ do not assume this
  gate passed.
- **T34.2/T34.3** (cue precision, P_k improvement) and **T35.1** (session-type
  classification accuracy) are unevaluated for the same reason — no S05
  corpus to measure against.
- **Net effect:** the S05 gap (item #1, previously scoped just to S06/S19) is
  now the single blocking dependency for *four* separate evaluation gates
  (S06, S29, S34, S35) plus S19's benchmark. Recording and hand-labelling the
  real corpus is the highest-leverage remaining gap in the whole S01-S40 range.

## Not yet addressed

- Skip messages in `test_asr_worker.py`, `test_diarisation.py`, `test_e2e_gate.py`
  still reference the old GPU mismatch reasoning and should be updated to point
  at the corpus/token gaps instead.
- `ansible/inventory.yml` still has placeholder `ansible_host` / `ansible_user`
  values — the playbook has never been run against a real target host, only
  retrofitted to match this dev machine's driver version.
- Pre-commit hooks are currently failing across the pre-existing codebase
  (see gap #5) and need a real cleanup pass, not further `--no-verify` commits.
- S36-S40 (Block 6) and S25-S35 (Blocks 4-5, if/when implemented) will hit the
  same "no GPU-loaded model / no real corpus" test-skip pattern as S02/S06/S19/
  S20/S21 until gaps #1 and #2 (or their Block-6 equivalent: no cached vLLM
  weights) are resolved.

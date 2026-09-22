# Self-improving loop: flashcards as a reward signal (Stage 1 status)

**Built (Stage 1, partial):** `src/services/quality/reward.py` (coverage, diversity,
weighted-geometric aggregate), `judge.py` (fail-open, OpenAI-compatible judge, Groq
model `openai/gpt-oss-20b` - not Qwen, confirmed available on the account's key),
`scorer.py` (runs inline at the end of `generate_study_materials`, consent-gated),
the `note_quality_traces` append-only table + migration `d1a7c3e5b9f2`
(no_update/no_delete RULEs like `corrections`, applied live), and the
`users.allow_cloud_scoring` consent flag. Unit-tested with synthetic vectors;
the scorer/judge path has also been run live (see Live run below).

**Not built yet:** Valkey async quality worker (scoring currently runs inline,
adding embedding+judge latency to the end of the run), MLflow logging, storing
flashcard source utterance ids (needed for the `validity` judge term - only
`provenance` is scored today), Spearman-rho validation against human ratings.

## Reward
R = weighted geometric mean of coverage(0.30), note_coverage(0.20), diversity(0.15),
validity(0.20, judge), provenance(0.15, judge). Weights and tau=0.5 are
**unvalidated priors**. Geometric so a collapsed term collapses R.
Circularity: the same local model writes notes and cards, so every term is scored
against the source transcript, and judged terms use a different model family
(Groq; model id and free-tier limits UNVERIFIED - check before configuring).
R is not trusted until Spearman rho vs human ratings (Label Studio) is shown.

## Optimization tiers
A (now, no training): prompt/chunk-size search, champion/challenger with rollback.
B: T5 relevance thresholds. C: DPO/SFT only with ~1k+ consented pairs + rented GPU.
Clustering last (T5 uses one label per session; low leverage).

## Live run: judge caught a real synthesis defect (2026-09-22)

Scoring a real session (`8ee8183d…`, "Agentic AI" lecture, 60 relevant utterances,
consent enabled for its test account) with the judge on found `provenance` at
**0.3** - most note sections judged unsupported by their cited utterances.
Inspecting the 10 sections individually showed this wasn't judge over-strictness:
4 of 10 had `body_md` literally equal to `"Source utt_ids: [...]"` - A2 had
echoed its own citation field as the note body instead of writing prose. This
passed every existing structural check (valid JSON, balanced KaTeX, non-empty
Mermaid, known citation IDs) because none of them checked that `body_md` was
actual content.

Fix: `validate_body_is_prose()` in `note_synthesis.py` (commit `d350379`) rejects
that stub pattern; the section is dropped like any other invalid one, siblings
survive. Verified live, not just in unit tests: cleared the session's notes,
re-ran `generate_study_materials` end-to-end, got 15 sections / 35 flashcards
with zero stub bodies. Re-scored: `provenance` **0.3 → 0.4**. A real but partial
improvement - it confirms the stub-echo bug was part of the problem, but the
larger remaining share is sections whose prose genuinely asserts more than the
utterances they cite, which is a prompt/grounding issue, not a structural one,
and is still open.

Practical note from this run: a full re-synthesis of a ~60-utterance session
OOM-killed `lis-asr-worker` twice at its default 4GB container limit (TEI 413s
on the batch, falls back to a local CPU model that needs more headroom); it
completed at 8GB. This is a pre-existing constraint of `EmbeddingClient`'s
pipeline-side batching (separate from `quality/scorer.py`'s own batching fix,
commit `8425438`), not something this task changed - worth its own fix later.

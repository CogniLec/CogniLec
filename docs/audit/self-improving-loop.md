# Self-improving loop: flashcards as a reward signal (Stage 1 status)

**Built (Stage 1, partial):** `src/services/quality/reward.py` (coverage, diversity,
weighted-geometric aggregate) and `judge.py` (fail-open, OpenAI-compatible judge).
Unit-tested with synthetic vectors only.

**Not built yet:** `note_quality_traces` append-only table + migration
(down_revision `c4d8e2a6f1b9`, no_update/no_delete RULEs like `corrections`),
`users.allow_cloud_scoring` consent flag (does not exist), Valkey quality worker,
MLflow logging, storing flashcard source utterance ids (needed for validity).

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

# ADR-011: GPU-Enabled Ensemble ASR (Supersedes Pre-filter)

## Status
Accepted

## Context
Original design (ADR-011 in Architecture v1.0) used HDBSCAN outlier score as pre-filter before A1 to save LLM calls.
With self-hosted GPU (v2.0), LLM calls are cheap/fixed-cost.

## Decision
Remove HDBSCAN pre-filter gate. Instead:
- Run dual-ASR ensemble (primary + secondary) on every session
- Cross-model disagreement → hallucination detector (S22)
- A1 relevance filter receives outlier score as PROMPT FEATURE, not gate
- For ambiguous utterances (~15%): ensemble voting across 2-3 LLM models
- Split vote → KEEP and flag for review (asymmetric cost: discard precision > recall)

## Consequences
- No relevant content lost to pre-filter
- Hallucination detection via ASR disagreement (v2.0 §3.1)
- Consensus voting where it matters (ambiguous cases)
- Fixed GPU cost makes this affordable

## Follow-up
- S21: Dual-ASR ensemble
- S22: Hallucination detection
- S41: A1 relevance filter with outlier feature
- S43: A1 ensemble voting

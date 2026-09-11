# ADR-012: Fine-Tuning Flywheel

## Status
Accepted

## Context
Long-term strategic value: fine-tune small specialist models on system's own corrected output.
Requires: corrected transcripts, human-verified relevance decisions, verified note quality.

## Decision
Data flywheel architecture:
1. **Collection**: Every correction (transcript edit, relevance override, note rating) stored with provenance
2. **Curation**: Automated quality filters + human review queue
3. **Training**: Periodic LoRA/QLoRA fine-tuning on:
   - ASR: Whisper/Canary on corrected transcripts (domain adaptation)
   - Embedding: Qwen3-Embedding on relevance-verified pairs
   - A1: Phi-3/Qwen on human-verified relevance decisions
   - A2: Phi-3/Qwen on human-rated note quality
4. **Evaluation**: A/B against base models on held-out eval set
5. **Deployment**: Canary → shadow → primary via model version registry

## Consequences
- Model improvement compounds over semester
- Small models (0.6B-3B) become competitive with large
- Requires human-in-the-loop for quality signal
- Training runs on GPU host (scheduled, low priority)

## Follow-up
- S12/S13: RLS + audit trail for corrections
- S65-S69: Fine-tuning pipeline
- S76: Full acceptance includes flywheel metrics

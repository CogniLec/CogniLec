# ADR-009: Anonymous Diarisation Only

## Status
Accepted

## Context
Speaker diarisation useful for transcript readability but:
- NFR-S4: No biometric data anywhere
- NFR-S5: Consent for recording, not identification
- Speaker identity irrelevant to topic-based filtering

## Decision
pyannote.audio 3.x for diarisation with strict constraints:
- Output: session-scoped anonymous tags (SPK_A, SPK_B, ...)
- Tags stored in `utterances.speaker_tag` (session-local only)
- NO voiceprints, embeddings, or biometric templates persisted
- Tags NEVER linked across sessions
- Tags DROPPED at note synthesis (A2 input has no speaker info)
- Diarisation optional: pipeline completes without it (S20 gate)

## Consequences
- Transcript readability improved (who said what in session)
- Zero privacy risk (no persistent identity)
- Symmetric filtering: lecturer aside discarded, student question retained
- Gate S20 validates NFR-S4 compliance

## Follow-up
- S19: ASR worker emits utterances
- S20: Diarisation step + gate
- S41: A1 filtering ignores speaker_tag

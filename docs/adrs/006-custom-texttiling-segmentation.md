# ADR-006: Custom TextTiling Segmentation

## Status
Accepted

## Context
Need sequential, contiguous, non-overlapping topic segments from ASR output.
Existing libraries (TextTiling, BERTopic segmentation) fail on noisy ASR:
- No word timestamps in standard libraries
- Fixed windows don't adapt to topic shift speed
- ASR errors create false boundaries

## Decision
Custom sequential segmentation over windowed embeddings:
- Overlapping windows of W utterances (W from S06 experimentation)
- Cosine similarity between adjacent windows
- Adaptive threshold: percentile-based on session's similarity distribution
- Output: ordered segments with boundary_score
- Every utterance belongs to exactly one segment

## Consequences
- Structurally valid segments guaranteed (contiguous, non-overlapping)
- Adapts to lecture style (fast vs slow topic shifts)
- No external library dependency for core algorithm
- P_k evaluation against hand labels (Gate S29)

## Follow-up
- S26: Context-window embedding
- S28: Boundary detection implementation
- S29: Segmentation evaluation gate

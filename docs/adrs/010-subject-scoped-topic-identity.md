# ADR-010: Subject-Scoped Topic Identity

## Status
Accepted

## Context
Topics accumulate across sessions within a subject (FR-5.3, FR-5.4, FR-5.5).
Cross-subject topic reconciliation explicitly NOT done.

## Decision
Per-subject topic clustering with cross-session identity:
- BERTopic clustering per session (segment-level embeddings)
- Centroid matching against existing subject topics
- Threshold: above → link existing, below → create new
- Incremental centroid update after each session
- Full re-cluster every N sessions (default 10, tighter for sessions 2-5)
- User-edited labels preserved across re-clustering
- Matching queries NEVER cross subject boundaries (RLS + partition)

## Consequences
- "Same topic taught across 3 sessions = 1 topic" (AC-4)
- New topics create new partitions naturally
- Cold start handled by more frequent re-clustering early on
- Subject isolation enforced at query level

## Follow-up
- S30: Topic clustering (BERTopic)
- S31: Topic labelling + keyword extraction
- S32: Cross-session topic identity

# ADR-014: Two-Phase Architecture (Live + Post-Session)

## Status
Accepted

## Context
Real-time constraints only apply to audio capture. Everything else can be durable, retryable, re-runnable.

## Decision
Strict two-phase separation:

**Phase 1: Live (Real-time)**
- Audio capture → chunk upload → preprocessing → ASR → transcript commit
- ONLY real-time dependencies: microphone, network, GPU for ASR
- NFR-R3: Transcript committed BEFORE any downstream stage starts
- State machine: created → recording → transcribed

**Phase 2: Post-Session (Background, Durable)**
- Embedding → segmentation → clustering → agents → notes → exports
- All stages: idempotent, cached, retryable, re-runnable
- Raw transcript = permanent source of truth
- Bad model call or pipeline bug never loses a lecture
- State machine: transcribed → processing → complete | failed

## Consequences
- Live phase minimal, testable independently
- Post-session phase can use heavy models, take hours
- Failure in post-session → retry from transcript, not re-capture
- Gate S20 validates live phase E2E

## Follow-up
- S14-S20: Live capture & ingestion
- S21-S24: Transcript integrity
- S25-S49: Post-session pipeline

# ADR-003: Event-Driven Pipeline Triggers

## Status
Accepted

## Context
Pipeline stages must trigger automatically:
- audio.chunk → preprocessing (real-time)
- session.transcribed → embedding (post-session)
- embedding complete → segmentation → clustering
- clustering complete → agent pipeline

## Decision
Use Prefect Events + Valkey Streams:
- Valkey Stream for audio.chunk (real-time, consumer groups)
- Prefect Events for session state transitions
- Each flow triggered by event, not polling
- Event payload contains session_id, subject_id, metadata

## Consequences
- Low latency for real-time stages
- Durable event log in Valkey
- Prefect UI shows event-driven flow runs
- Consumer group semantics for chunk processing

## Follow-up
- S16: Chunk upload API + Valkey Stream producer
- S17: Preprocessing worker consuming audio.chunk
- S27: Prefect flow with event trigger

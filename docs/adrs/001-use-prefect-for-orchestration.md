# ADR-001: Use Prefect for Pipeline Orchestration

## Status
Accepted

## Context
Need durable, retryable, observable orchestration for ML pipeline with:
- Complex DAGs with ML/model dependencies
- Event-driven triggers (audio.chunk, session.transcribed)
- Caching and idempotency per task
- Integration with existing Python stack

Alternatives considered: Airflow (heavy, JVM), Dagster (steeper learning), custom (reinventing wheel).

## Decision
Use Prefect 3.x as orchestration engine.
- Python-native, fits stack
- Task caching on (session_id, model_version)
- Event-driven via Prefect events
- Worker pools: ml-pool (GPU), llm-pool (GPU/CPU), cpu-pool
- LangGraph for intra-task agent orchestration

## Consequences
- Team learns Prefect patterns
- Deployment complexity (server + workers)
- Migration path if needed: Prefect flows are Python functions
- Cost: Prefect Cloud or self-hosted server

## Follow-up
- ADR-002: Worker pool topology
- ADR-003: Event schema for triggers

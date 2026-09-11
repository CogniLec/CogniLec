# ADR-007: Six Independent LLM Agents

## Status
Accepted

## Context
Post-session pipeline has 6 distinct LLM tasks:
- A1: Relevance filtering (on/off-topic)
- A2: Note synthesis (full transcript → structured notes)
- A3: History context (cross-session topic continuity)
- A4: Visual enrichment (diagrams, images)
- A5: Question generation (flashcards, mock tests)
- A6: Syllabus extraction (first session → syllabus DB)

Must be auditable, isolated, independently versioned.

## Decision
Six independent agents, no inter-agent communication:
- Each agent: single LLM call with structured output (Pydantic schema)
- Prompt versioned in LangFuse, referenced by version
- Constrained decoding (Outlines/XGrammar) on local models
- LiteLLM router for failover ladder
- LangGraph orchestrates sequentially, not collaboratively
- `agent_runs` table: complete audit trail per invocation

## Consequences
- No agent sees another's output (isolation enforced structurally)
- Debugging: re-run single agent with same inputs
- Prompt regression testing via promptfoo per agent
- Cost attribution per agent per session

## Follow-up
- S36: LLM serving infrastructure
- S37: LiteLLM router + failover
- S38: Structured output + schema registry
- S39: LangFuse tracing + agent_runs
- S40: Prompt versioning + promptfoo
- S41-S46: Individual agent implementations

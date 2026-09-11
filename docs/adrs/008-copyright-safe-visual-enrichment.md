# ADR-008: Copyright-Safe Visual Enrichment

## Status
Accepted

## Context
A4 (Visual Enrichment) must generate diagrams/images without copyright risk.
No input image parameter allowed in generation service.

## Decision
Three-tier image sourcing (strict priority):
1. **Text-based**: Mermaid, KaTeX, ASCII, PlantUML — generated from scratch by LLM
2. **Openly-licensed retrieval**: Wikimedia Commons, OpenClipart, NASA, etc. — licence verified
3. **Generation from scratch**: LLM + diffusion (if GPU allows) — never from copyrighted reference

Database constraint: `note_assets` table requires `source_url` + `licence` NOT NULL for `web_image` type.
Image generation service has NO `input_image` parameter — structurally impossible to pass copyrighted ref.

## Consequences
- Zero copyright liability by design
- Quality trade-off: text diagrams first, retrieval second
- Licence compliance enforced at DB level
- A4 agent only outputs Mermaid/KaTeX or verified open licences

## Follow-up
- S10: note_assets schema with licence constraint
- S59-S64: Visual enrichment pipeline
- S63: FR-4.9 boundary gate

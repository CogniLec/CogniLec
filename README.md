# Lecture Intelligence System (LIS)

> Point it at a classroom. It listens, figures out what's actually being taught, and turns a semester of lectures into notes, flashcards, and mock tests that get better every session.

---

## What This Is

LIS is a system that records live classroom or meeting audio and turns it into structured, topic-organised study material — without ever knowing or caring *who* is speaking.

Most transcription tools give you a wall of undifferentiated text: everything the microphone heard, in the order it heard it, with no sense of what mattered. LIS is built around a different idea: **identify the topic, not the speaker.** A relevant question from a student in the back row belongs in the notes. An off-topic aside from the lecturer does not. The system decides that by *what was said*, never by *who said it* — no voice enrolment, no speaker identification, no biometric data, anywhere.

Everything the system produces — notes, flashcards, mock tests, coverage tracking against the syllabus — accumulates coherently across a whole semester, per subject, rather than existing as disposable output from one lecture.

## What We're Building

A pipeline with two phases:

**Live**, while the lecture happens: audio is captured, cleaned, and transcribed in real time, with word-level timestamps.

**Post-session**, in the background: the transcript is embedded, segmented into topics, filtered for relevance, and synthesised into notes by a set of specialised LLM agents — each one independent, none of them chatting with each other, all of them auditable. Board photos and textbook pages get OCR'd in. Diagrams are drawn as text (Mermaid, KaTeX) where possible, retrieved from openly-licensed sources where not, and generated from scratch — never from a copyrighted reference — as a last resort.

The result, per subject: a searchable, cross-referenced knowledge base that knows what's been taught, what the syllabus still expects, and how to quiz you on it.

### Core design decisions worth knowing up front

- **Topic-first, not speaker-first.** No identity is ever inferred or stored about who's talking.
- **Two-phase architecture.** Live capture is the only real-time dependency. Everything else is durable, retryable, and re-runnable — the raw transcript is the permanent source of truth, so a bad model call or a pipeline bug never loses a lecture.
- **Six independent LLM agents**, not a collaborative mesh: relevance filtering, note synthesis, history context, visual enrichment, question generation, syllabus extraction. Isolation is enforced structurally, not by convention.
- **User-defined subjects**, each an isolated namespace. Topics *within* a subject are discovered automatically by clustering; the system never tries to reconcile topics *across* subjects.
- **A separate syllabus database**, linked to the main store, so the system can track what's been covered against what's expected.
- **Copyright handled structurally, not by policy.** The image-generation service has no parameter for an input image — a restricted picture cannot reach it because there's no field to put it in.
- **Self-hosted GPU inference**, which changes what's affordable: dual-ASR ensembles to catch hallucination, full-transcript note synthesis instead of chunked, and — the actual long-term payoff — fine-tuning small specialist models on the system's own corrected output as it accumulates.

## Documents in This Project

| Document | What it covers |
|---|---|
| **Requirements Specification (SRS) v1.0** | The functional and non-functional requirements — what the system must do, organised into FR-1 through FR-7 plus NFRs, with acceptance criteria |
| **Technical Architecture v1.0** | The system design: runtime topology, the orchestration split (Prefect / LangGraph / n8n), agent contracts, database schema, ADRs |
| **GPU Architecture Revision v2.0** | How owned GPU capacity changes the design — ensemble ASR, consensus voting, fine-tuning as the real strategic payoff |
| **Stack Manifest v1.1 + Addendum v2.1** | The complete open-source tool inventory across every layer — containers, databases, ML serving, observability, CI/CD — with licence flags and a tiered adoption plan |
| **Implementation Plan v1.0** | 76 build stages across 14 blocks, each a full vertical slice with test cases, gated by 7 hard checkpoints |

Start with the SRS if you want to know *what* the system does. Start with the Implementation Plan if you want to know *what gets built, in what order*.

## Status

Architecture and planning stage. Nothing has shipped yet. **The first real milestone (Gate 1) is a two-to-four-day benchmark** measuring real classroom audio quality against several ASR models — everything else in the plan depends on that number, so it happens before any other code is written.

## The One-Line Version

A system that listens to lectures, figures out what mattered, and never has to know who was talking to do it.

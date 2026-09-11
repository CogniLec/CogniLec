# ADR-018: Local-First ASR and Embedding (No Hosted APIs)

## Status
Accepted

## Context
S06 bake-off and production ASR/embedding must run fully local.
No dependency on OpenAI Whisper API, AssemblyAI, or other hosted services.

## Decision
**ASR Models (all open weights, local inference)**:
1. Whisper large-v3 (OpenAI, open weights)
2. Whisper large-v3-turbo (OpenAI, open weights)
3. Canary-Qwen 2.5B (NVIDIA, open weights)
4. Parakeet TDT 1.1B (NVIDIA, open weights)

**Inference Engine**: `faster-whisper` (CTranslate2 backend) for all Whisper variants.
- 4x faster than PyTorch Whisper
- Supports int8_float16 quantization
- Word-level timestamps via wav2vec2 forced alignment (WhisperX-style)

**Embedding Model**: Qwen3-Embedding-0.6B via sentence-transformers or TEI.
- 1024 dimensions
- Apache 2.0 license
- Instruction-tuned for retrieval/clustering tasks

**Reference Ceiling**: Removed hosted API comparison.
- Bake-off compares 4 open models against each other
- Best open model becomes production baseline
- Human transcription (S05) is ground truth, not hosted API

## Consequences
- Zero recurring API costs for ASR/embedding
- Full data privacy (audio never leaves GPU host)
- Reproducible benchmarks (same models, same hardware)
- Model upgrades = local re-bake-off, not API migration

## Follow-up
- S06: Bake-off with 4 local models
- S19: ASR worker uses faster-whisper
- S25: Embedding service uses TEI/sentence-transformers
- S36: LLM ladder still allows hosted API for agents (ADR-016)

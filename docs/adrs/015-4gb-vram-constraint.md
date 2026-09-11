# ADR-015: 4GB VRAM Constraint — Model Selection & Quantization

## Status
Accepted

## Context
GPU host has Quadro T1000 Mobile (4GB VRAM). This constrains all model choices.

## Decision
All GPU workloads must fit in 4GB VRAM with headroom:

**ASR (S19/S21)**:
- Primary: `faster-whisper` (CTranslate2) with `large-v3-turbo` at float16 (~2.5GB)
- Secondary: Parakeet TDT 1.1B at float16 (~2.5GB) or 8-bit (~1.5GB)
- Whisper large-v3 only at 8-bit via bitsandbytes (~3.5GB)
- Canary-Qwen 2.5B only at 8-bit (~3GB)

**Embedding (S25)**:
- Qwen3-Embedding-0.6B only (1024 dim, ~1.5GB FP16)
- 4B/8B variants excluded (too large even quantized)

**LLM Agents (S36)**:
- Tier 1 Local: Phi-3-mini-3.8B-4bit (~2.5GB) or Qwen2.5-3B-4bit (~2GB)
- Tier 2 CPU: llama.cpp 7B-4bit (system RAM, slow)
- Tier 3 Hosted: OpenAI/Anthropic/etc. (no VRAM)
- No local 7B+ models

**Fine-tuning (S65+)**:
- QLoRA 4-bit only, batch size 1, gradient accumulation
- Offload optimizer to CPU if needed

## Consequences
- Model quality ceiling lower than 24GB+ GPU setups
- 8-bit quantization mandatory for larger models
- Sequential model loading (not concurrent) for S06 bake-off
- LLM agent quality depends on hosted API fallback

## Follow-up
- S02: CUDA matrix documents 4GB constraint
- S06: Bake-off with 8-bit models
- S19: ASR worker uses faster-whisper
- S25: Embedding service uses Qwen3-0.6B
- S36: LLM ladder starts at small local models

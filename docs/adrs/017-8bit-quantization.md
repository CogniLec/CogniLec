# ADR-017: 8-Bit Quantization for ASR & Embedding Models

## Status
Accepted

## Context
4GB VRAM requires quantization for models >2GB FP16.
bitsandbytes 0.50.2 supports 8-bit linear layers for PyTorch 2.5+.

## Decision
Apply 8-bit quantization via bitsandbytes for:
- **Whisper large-v3** (ASR): Load via `faster-whisper` with `device="cuda", compute_type="int8_float16"`
- **Canary-Qwen 2.5B** (ASR): Load via transformers with `load_in_8bit=True`
- **Qwen3-Embedding-0.6B** (Embedding): FP16 fits (~1.5GB), 8-bit optional (~1GB)

**Excluded from quantization** (already small):
- Whisper large-v3-turbo (~2.5GB FP16)
- Parakeet TDT 1.1B (~2.5GB FP16)
- Phi-3-mini-3.8B-4bit (already 4-bit AWQ)

**Quality validation**: S06 bake-off runs ALL models at production quantization.
Gate thresholds (WER <20%, purity >0.60) apply to quantized models.

## Consequences
- ~40% VRAM reduction for large models
- ~10-15% latency increase (acceptable for batch post-session)
- Quality degradation measured and gated in S06
- CTranslate2 int8_float16 faster than bitsandbytes for Whisper

## Follow-up
- S02: bitsandbytes in CUDA matrix
- S06: Bake-off with quantized models
- S19: ASR worker uses CTranslate2 int8
- S25: Embedding service quantization config

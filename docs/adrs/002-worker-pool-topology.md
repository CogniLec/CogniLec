# ADR-002: Worker Pool Topology

## Status
Accepted

## Context
Different pipeline stages have different resource requirements:
- ASR/Embedding: GPU required, memory-intensive
- LLM serving: GPU required (or CPU fallback), VRAM-sensitive
- Database/Preprocessing: CPU only
- Fine-training: GPU, long-running, high memory

## Decision
Three Prefect worker pools:
1. **ml-pool** (GPU): ASR, Embedding, Segmentation, Clustering
   - 1-2 workers, GPU-enabled, 8GB+ RAM each
   - Processes one session at a time (VRAM constraint)
2. **llm-pool** (GPU/CPU): LLM agents (A1-A6)
   - Tier 1: Local Phi-3-mini-3.8B-4bit (GPU)
   - Tier 2: CPU llama.cpp 7B-4bit (CPU)
   - Tier 3: Hosted API (no GPU)
3. **cpu-pool** (CPU): Preprocessing, API, DB migrations, Eval
   - 4+ workers, no GPU

## Consequences
- Clear resource isolation
- GPU workers are bottleneck (4GB VRAM)
- LLM pool handles fallback ladder
- CPU pool scales horizontally

## Follow-up
- S02: GPU host provisioning
- S36: LLM serving infrastructure

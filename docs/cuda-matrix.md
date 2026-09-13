# CUDA Version Matrix — Single Source of Truth
#
# All GPU Dockerfiles MUST reference these versions via build ARGs.
# CI enforces consistency (see .github/workflows/ci.yml: cuda-matrix-check).
#
# Update this table ONLY when intentionally upgrading the entire GPU stack.
# Changing one component without others breaks compatibility.

| Component              | Version      | Notes                                                    |
|------------------------|--------------|----------------------------------------------------------|
| NVIDIA Driver          | 580.x        | Held via `apt-mark hold` on host (server-open variant)   |
| CUDA Toolkit           | 12.6         | Base image: `nvidia/cuda:12.6-cudnn-runtime-ubuntu22.04` |
| cuDNN                  | 9.5.x        | Bundled in base image                                    |
| PyTorch                | 2.5.1        | Build tag: `cu126`                                       |
| torchvision            | 0.20.1       | Build tag: `cu126`                                       |
| torchaudio             | 2.5.1        | Build tag: `cu126`                                       |
| flash-attn             | 2.8.3        | Requires CUDA >= 12.0, PyTorch >= 2.2                    |
| bitsandbytes           | 0.50.2       | Supports CUDA 12.x                                       |
| faiss-gpu              | 1.7.2        | CUDA 12.x compatible                                     |
| ctranslate2            | 4.8.2        | Used by faster-whisper                                   |
| faster-whisper         | 1.1.0        | CTranslate2 backend for Whisper                          |
| transformers           | 4.44.2       | Compatible with PyTorch 2.5                              |
| accelerate             | 0.33.0       | Compatible with PyTorch 2.5                              |
| sentence-transformers  | 3.2.0        | Embedding inference                                      |
| bertopic               | 0.16.0       | Topic modeling                                           |
| umap-learn             | 0.5.6        | Dimensionality reduction                                 |
| hdbscan                | 0.8.33       | Clustering                                               |

## Version Pinning Rules

1. **CUDA version is the anchor** — all other versions must be compatible with CUDA 12.6
2. **PyTorch build tag MUST match** — `cu126` for all torch packages
3. **Driver version is host-only** — containers use base image's CUDA runtime
4. **No floating tags** — every image uses explicit versions
5. **Security updates** — patch versions may be bumped without review if ABI-compatible

## Upgrade Procedure

1. Update this table with new versions
2. Update `docker/base-gpu.Dockerfile` ARGs
3. Rebuild `base-gpu` image
4. Run full CI pipeline (including `docker-build` and `cuda-matrix-check` jobs)
5. Run S06 bake-off locally to verify model compatibility
6. Tag release

## Compatibility Notes

- **flash-attn 2.8.3**: Last version supporting Ampere (RTX 30-series) and older; Hopper (H100) needs flash-attn 3.x + CUDA 12.3+
- **bitsandbytes 0.50.x**: Requires PyTorch 2.4+; 0.49.x for PyTorch 2.3
- **faiss-gpu 1.7.x**: Last version with prebuilt CUDA 12 wheels; 1.8+ may need source build
- **ctranslate2 4.8.x**: Supports CUDA 12.x; 4.7.x for CUDA 11.x
- **Qwen3-Embedding**: Requires transformers >= 4.44.0

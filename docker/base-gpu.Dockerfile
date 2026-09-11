# Base GPU Dockerfile — Single source for all GPU-enabled services
#
# Build args come from docs/cuda-matrix.md (enforced by CI)
# Usage: docker build --target base -t lis/base-gpu:latest -f docker/base-gpu.Dockerfile .
#
# Targets:
#   base         - CUDA runtime + Python + core ML deps (used by all GPU services)
#   asr          - ASR worker (faster-whisper, ctranslate2)
#   embedding    - Embedding service (TEI / sentence-transformers)
#   llm          - LLM serving (vLLM / SGLang) — NOT USED ON 4GB VRAM, kept for reference
#   training     - Fine-tuning (bitsandbytes, flash-attn, peft)

ARG CUDA_VERSION=12.6
ARG CUDNN_VERSION=9.5
ARG UBUNTU_VERSION=22.04
ARG PYTHON_VERSION=3.12

# =============================================================================
# BASE STAGE — Common GPU runtime for all services
# =============================================================================
FROM nvidia/cuda:${CUDA_VERSION}-cudnn-runtime-ubuntu${UBUNTU_VERSION} AS base

# ---- Build arguments (from cuda-matrix.md) ----
ARG PYTORCH_VERSION=2.5.1
ARG PYTORCH_CUDA=cu126
ARG FLASH_ATTN_VERSION=2.8.3
ARG BITSANDBYTES_VERSION=0.50.2
ARG FAISS_GPU_VERSION=1.7.2
ARG CTRANSLATE2_VERSION=4.8.2
ARG FASTER_WHISPER_VERSION=1.1.0
ARG TRANSFORMERS_VERSION=4.44.2
ARG ACCELERATE_VERSION=0.33.0
ARG SENTENCE_TRANSFORMERS_VERSION=3.2.0
ARG BERTOPIC_VERSION=0.16.0
ARG UMAP_LEARN_VERSION=0.5.6
ARG HDBSCAN_VERSION=0.8.33

# ---- System dependencies ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3=${PYTHON_VERSION}* \
    python3-pip \
    python3-venv \
    git \
    curl \
    ca-certificates \
    ffmpeg \
    libsndfile1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ---- Python environment ----
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

# Create virtual environment
ENV VENV_PATH=/opt/venv
RUN uv venv ${VENV_PATH} --python python3
ENV PATH="${VENV_PATH}/bin:${PATH}"

# ---- PyTorch (CUDA 12.6) ----
RUN uv pip install --no-cache-dir \
    torch==${PYTORCH_VERSION} \
    torchvision==0.20.1 \
    torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/${PYTORCH_CUDA}

# ---- Core ML dependencies ----
RUN uv pip install --no-cache-dir \
    flash-attn==${FLASH_ATTN_VERSION} \
    bitsandbytes==${BITSANDBYTES_VERSION} \
    faiss-gpu==${FAISS_GPU_VERSION} \
    ctranslate2==${CTRANSLATE2_VERSION} \
    faster-whisper==${FASTER_WHISPER_VERSION} \
    transformers==${TRANSFORMERS_VERSION} \
    accelerate==${ACCELERATE_VERSION} \
    sentence-transformers==${SENTENCE_TRANSFORMERS_VERSION} \
    bertopic==${BERTOPIC_VERSION} \
    umap-learn==${UMAP_LEARN_VERSION} \
    hdbscan==${HDBSCAN_VERSION} \
    huggingface-hub==0.24.7 \
    safetensors==0.4.5 \
    tokenizers==0.19.1

# ---- Common runtime deps ----
RUN uv pip install --no-cache-dir \
    numpy==1.26.4 \
    pandas==2.2.2 \
    scipy==1.13.1 \
    scikit-learn==1.5.1 \
    pyyaml==6.0.1 \
    python-dotenv==1.0.1 \
    structlog==24.1.0 \
    prometheus-client==0.20.0 \
    opentelemetry-api==1.27.0 \
    opentelemetry-sdk==1.27.0 \
    opentelemetry-instrumentation-fastapi==0.47b0 \
    opentelemetry-instrumentation-sqlalchemy==0.47b0 \
    opentelemetry-instrumentation-redis==0.47b0 \
    opentelemetry-exporter-otlp==1.27.0

# ---- CUDA memory optimization ----
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:128,expandable_segments:True
ENV CUDA_VISIBLE_DEVICES=0

# ---- Health check ----
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import torch; assert torch.cuda.is_available(); print('GPU OK')" || exit 1

# =============================================================================
# ASR STAGE — Audio transcription worker
# =============================================================================
FROM base AS asr

ARG WHISPER_MODEL=large-v3-turbo
ARG WHISPER_DEVICE=cuda
ARG WHISPER_COMPUTE_TYPE=float16
ARG WHISPER_BEAM_SIZE=5
ARG WHISPER_BATCH_SIZE=16

# ASR-specific deps
RUN uv pip install --no-cache-dir \
    whisper-normalizer==0.1.0 \
    jiwer==3.0.4 \
    webrtcvad==2.0.10 \
    pydub==0.25.1 \
    opuslib==3.0.1 \
    torchaudio==2.5.1

# Model cache directory
ENV HF_HOME=/models/huggingface \
    WHISPER_MODEL=${WHISPER_MODEL} \
    WHISPER_DEVICE=${WHISPER_DEVICE} \
    WHISPER_COMPUTE_TYPE=${WHISPER_COMPUTE_TYPE}

WORKDIR /app
COPY src/workers/asr_worker.py /app/
COPY src/workers/preprocessing.py /app/

ENTRYPOINT ["python", "asr_worker.py"]

# =============================================================================
# EMBEDDING STAGE — Embedding service (TEI compatible)
# =============================================================================
FROM base AS embedding

ARG EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
ARG EMBEDDING_DIM=1024
ARG EMBEDDING_BATCH_SIZE=32
ARG EMBEDDING_MAX_LENGTH=512

RUN uv pip install --no-cache-dir \
    text-embeddings-inference==1.5.0 \
    || echo "TEI install failed, using sentence-transformers fallback"

ENV HF_HOME=/models/huggingface \
    EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    EMBEDDING_DIM=${EMBEDDING_DIM}

WORKDIR /app
COPY src/ml/embedding_service.py /app/

ENTRYPOINT ["python", "embedding_service.py"]

# =============================================================================
# LLM STAGE — Local LLM serving (reference only, not used on 4GB VRAM)
# =============================================================================
FROM base AS llm

ARG LLM_MODEL=microsoft/Phi-3-mini-4k-instruct
ARG LLM_QUANTIZATION=awq
ARG LLM_DTYPE=half
ARG LLM_GPU_MEMORY_UTILIZATION=0.85
ARG LLM_MAX_MODEL_LEN=4096
ARG LLM_TENSOR_PARALLEL_SIZE=1

# vLLM - only for reference, requires >8GB VRAM
RUN uv pip install --no-cache-dir \
    vllm==0.6.3 \
    || echo "vLLM install failed - expected on 4GB VRAM"

ENV HF_HOME=/models/huggingface \
    LLM_MODEL=${LLM_MODEL}

WORKDIR /app
# ENTRYPOINT for vLLM would go here if VRAM allowed

# =============================================================================
# TRAINING STAGE — Fine-tuning with LoRA/QLoRA
# =============================================================================
FROM base AS training

ARG PEFT_VERSION=0.12.0
ARG TRAL_VERSION=0.9.0
ARG WANDB_VERSION=0.17.0

RUN uv pip install --no-cache-dir \
    peft==${PEFT_VERSION} \
    trl==${TRAL_VERSION} \
    wandb==${WANDB_VERSION} \
    datasets==2.21.0 \
    evaluate==0.4.3 \
    rouge-score==0.1.2 \
    nltk==3.8.1

ENV HF_HOME=/models/huggingface \
    WANDB_DIR=/workspace/wandb

WORKDIR /app
COPY src/ml/training/ /app/

# =============================================================================
# DEVELOPMENT STAGE — Full environment with dev tools
# =============================================================================
FROM base AS dev

RUN uv pip install --no-cache-dir \
    jupyter==1.0.0 \
    jupyterlab==4.2.5 \
    ipykernel==6.29.5 \
    matplotlib==3.9.2 \
    seaborn==0.13.2 \
    plotly==5.23.0 \
    pytest==8.3.2 \
    pytest-asyncio==0.23.8 \
    pytest-cov==5.0.0 \
    hypothesis==6.101.2 \
    ruff==0.6.9 \
    mypy==1.11.2 \
    sqlfluff==3.1.0

WORKDIR /workspace

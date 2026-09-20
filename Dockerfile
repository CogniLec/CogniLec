# API container — previously the only piece of this stack that wasn't
# containerized at all (it ran as a bare `uvicorn` process). That meant it
# had no restart policy and didn't survive a host/process interruption,
# unlike every other service in docker-compose.yml (all of which now have
# `restart: unless-stopped`).
FROM python:3.12-slim

# build-essential (gcc): sentence-transformers' local embedding fallback
# (src/ml/embedding/client.py, used when TEI is unreachable or rejects a
# batch as too large) can trigger a Triton JIT-compiled kernel path on
# real-sized batches -- confirmed live: "RuntimeError: Failed to find C
# compiler" only appeared on a real 5-minute lecture's utterance batch,
# not on trivial test payloads, because Triton only compiles above some
# batch-size/sequence-length threshold.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
# vendor/ holds local path-dependency shims (frozendict, text-unidecode --
# gap #22 copyleft-license replacements) that `uv sync` resolves against;
# without it, "Distribution not found at: file:///app/vendor/..." fails
# the build immediately. README.md is needed too -- this project installs
# itself editable, and pyproject.toml's `readme = "README.md"` field makes
# hatchling refuse to build without it present.
COPY vendor ./vendor
RUN uv sync --frozen --no-dev

COPY src ./src
COPY config ./config
COPY alembic.ini ./

ENV PATH="/app/.venv/bin:$PATH"

# ctranslate2 (faster-whisper's backend) needs libcublas.so.12/
# libcudnn.so.9 at runtime for GPU decoding -- confirmed live (docs/
# gaps.md #20): without this, ASR fails with "Library libcublas.so.12 is
# not found or cannot be loaded" even with a real GPU device reservation,
# because python:3.12-slim ships no CUDA runtime at all and these
# libraries aren't on any default linker search path even once installed
# (nvidia-cublas-cu12/nvidia-cudnn-cu12, now real pyproject.toml
# dependencies -- see pyproject.toml comment -- rather than a one-off
# manual install that doesn't survive `uv sync`). This is the same
# per-invocation LD_LIBRARY_PATH fix gap #20 proved works for the dev
# venv, made persistent here for the container.
ENV LD_LIBRARY_PATH="/app/.venv/lib/python3.12/site-packages/nvidia/cublas/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cudnn/lib"

EXPOSE 8123

# Runs migrations (via DATABASE_URL, the superuser role) before serving,
# so a fresh deployment doesn't need a separate manual `alembic upgrade
# head` step -- safe to run on every start, it's a no-op once the schema
# is current.
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.api.main:app --host 0.0.0.0 --port 8123"]

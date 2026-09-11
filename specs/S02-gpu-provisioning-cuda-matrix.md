# S02 — GPU Host Provisioning & CUDA Matrix Pin
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Provision the GPU host (Quadro T1000 Mobile, 4GB VRAM) with pinned NVIDIA driver, container toolkit, Docker, and a single-source CUDA version matrix that all GPU Dockerfiles must reference.

**Component Boundaries:**
- **Allowed:** Ansible playbook, `docs/cuda-matrix.md`, `docker/base-gpu.Dockerfile`, `/etc/apt/preferences.d/nvidia-driver` hold file
- **Off-limits:** Application code, docker-compose.yml (S03), ML models (S06+)

**Tech Stack & Version Pinning (from `docs/cuda-matrix.md`):**
| Component | Version | Source |
|-----------|---------|--------|
| NVIDIA Driver | 560.x | Host package |
| CUDA Toolkit | 12.6 | Base image |
| cuDNN | 9.5.x | Base image |
| PyTorch | 2.5.1+cu126 | PyPI (cu126 index) |
| flash-attn | 2.8.3 | PyPI |
| bitsandbytes | 0.50.2 | PyPI |
| faiss-gpu | 1.7.2 | PyPI |
| ctranslate2 | 4.8.2 | PyPI |
| faster-whisper | 1.1.0 | PyPI |
| Base Docker Image | `nvidia/cuda:12.6-cudnn-runtime-ubuntu22.04` | NVIDIA |

---

### 2. State Machine & Domain Schemas

**`docs/cuda-matrix.md` Table Schema:**
```markdown
| Component | Version | Notes |
|-----------|---------|-------|
| NVIDIA Driver | 560.x | Held via apt-mark hold |
| CUDA | 12.6 | Base image tag |
| cuDNN | 9.5.x | Bundled |
| PyTorch | 2.5.1 | Build tag: cu126 |
| ... | ... | ... |
```

**Ansible Inventory (`ansible/inventory.yml`):**
```yaml
all:
  hosts:
    gpu-host:
      ansible_host: <IP>
      ansible_user: <user>
  vars:
    nvidia_driver_version: "560"
    cuda_version: "12.6"
    docker_version: "latest"
```

**`docker/base-gpu.Dockerfile` Build ARGs:**
```dockerfile
ARG CUDA_VERSION=12.6
ARG CUDNN_VERSION=9.5
ARG UBUNTU_VERSION=22.04
ARG PYTORCH_VERSION=2.5.1
ARG PYTORCH_CUDA=cu126
ARG FLASH_ATTN_VERSION=2.8.3
ARG BITSANDBYTES_VERSION=0.50.2
ARG FAISS_GPU_VERSION=1.7.2
ARG CTRANSLATE2_VERSION=4.8.2
ARG FASTER_WHISPER_VERSION=1.1.0
# ... all from cuda-matrix.md
```

**Driver Hold Config (`/etc/apt/preferences.d/nvidia-driver`):**
```
Package: nvidia-driver-560*
Pin: version 560.*
Pin-Priority: 1001
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Command |
|------|--------|---------|
| 1 | Write Ansible playbook | `ansible-playbook site.yml` |
| 2 | Install NVIDIA driver 560 (held) | `apt-mark hold nvidia-driver-560*` |
| 3 | Install NVIDIA Container Toolkit | `curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \| gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg` |
| 4 | Install Docker Engine | `apt-get install -y docker-ce docker-ce-cli containerd.io` |
| 5 | Configure Docker for GPU | `nvidia-ctk runtime configure --runtime=docker` |
| 6 | Write `docs/cuda-matrix.md` | Exact table from spec |
| 7 | Write `docker/base-gpu.Dockerfile` | Multi-stage with ARGs |
| 8 | Build base-gpu image | `docker build --target base -t lis/base-gpu:latest -f docker/base-gpu.Dockerfile .` |
| 9 | Verify GPU access in container | `docker run --gpus all lis/base-gpu:latest nvidia-smi` |
| 10 | Verify PyTorch CUDA version | `docker run --gpus all lis/base-gpu:latest python -c "import torch; print(torch.version.cuda)"` |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Driver/kernel version mismatch | Reboot host after driver install; `dkms status` |
| CUDA version mismatch in container | CI check (`cuda-matrix-check` job) fails build |
| OOM on base image build | Reduce parallel builds: `MAX_JOBS=4` |
| flash-attn build fails | Ensure ninja installed; `pip install ninja` |

---

### 4. Code Style & Architecture Constraints

- **Single source of truth:** `docs/cuda-matrix.md` — all versions defined here
- **CI enforcement:** `cuda-matrix-check` job fails if any GPU Dockerfile diverges
- **Base image:** Always `nvidia/cuda:12.6-cudnn-runtime-ubuntu22.04`
- **No host CUDA toolkit** — only driver + container toolkit needed
- **Driver held** against unattended upgrades (security vs stability trade-off)
- **4GB VRAM constraint** documented: all models must fit with headroom

---

### 5. API & Interface Contracts

**Ansible Playbook CLI:**
```bash
ansible-playbook -i ansible/inventory.yml ansible/site.yml --tags gpu
```

**Docker Build CLI:**
```bash
# Base image (used by all GPU services)
docker build --target base \
  --build-arg CUDA_VERSION=12.6 \
  --build-arg PYTORCH_VERSION=2.5.1 \
  -t lis/base-gpu:latest \
  -f docker/base-gpu.Dockerfile .

# ASR-specific image
docker build --target asr \
  -t lis/asr-worker:latest \
  -f docker/base-gpu.Dockerfile .
```

**Verification Commands:**
```bash
# Host
nvidia-smi
apt-mark showhold | grep nvidia

# Container
docker run --rm --gpus all lis/base-gpu:latest nvidia-smi
docker run --rm --gpus all lis/base-gpu:latest python -c "
import torch
print('CUDA:', torch.version.cuda)
print('cuDNN:', torch.backends.cudnn.version())
assert torch.version.cuda == '12.6'
import flash_attn; print('flash-attn OK')
import bitsandbytes; print('bitsandbytes OK')
import faiss; print('faiss OK')
import ctranslate2; print('ctranslate2 OK')
"
```

---

### 6. Dependency & Environment Configuration

**Host `.env` (for Ansible):**
```bash
NVIDIA_DRIVER_VERSION=560
CUDA_VERSION=12.6
DOCKER_VERSION=latest
```

**Container Environment (base-gpu.Dockerfile):**
```dockerfile
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:128,expandable_segments:True
ENV CUDA_VISIBLE_DEVICES=0
ENV HF_HOME=/models/huggingface
```

**Secrets:** None at this stage (handled in S03 via SOPS)

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T02.1 | I | `docker run --gpus all base-gpu nvidia-smi` | Lists GPU (T1000) |
| T02.2 | I | `torch.version.cuda` in container | Equals "12.6" |
| T02.3 | I | `import flash_attn` forward pass | No error |
| T02.4 | S | `apt-mark showhold` | Shows nvidia-driver-560* |
| T02.5 | U | CI `cuda-matrix-check` job | Fails on version mismatch |
| T02.6 | I | `bitsandbytes.nn.Linear8bitLt` import | Works (8-bit support) |

**Verification Script (`scripts/verify_s02.sh`):**
```bash
#!/bin/bash
set -euo pipefail
echo "=== Host GPU ==="
nvidia-smi
echo "=== Driver Hold ==="
apt-mark showhold | grep nvidia
echo "=== Container GPU ==="
docker run --rm --gpus all lis/base-gpu:latest nvidia-smi
echo "=== PyTorch CUDA ==="
docker run --rm --gpus all lis/base-gpu:latest python -c "import torch; assert torch.version.cuda == '12.6'; print('OK')"
echo "=== ML Libs ==="
docker run --rm --gpus all lis/base-gpu:latest python -c "
import flash_attn, bitsandbytes, faiss, ctranslate2
print('All ML libs import OK')
"
echo "=== S02 VERIFIED ==="
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| Driver/library mismatch | `nvidia-smi` fails in container | Rebuild container after host driver update; pin driver version |
| CUDA version drift | CI `cuda-matrix-check` fails | Update Dockerfile ARGs to match `cuda-matrix.md` |
| flash-attn build fails | `pip install flash-attn` errors | Install ninja; use manylinux wheel; check PyTorch version |
| OOM on 4GB | Container kills | Reduce `PYTORCH_CUDA_ALLOC_CONF`; use 8-bit quantization |
| Unattended upgrade breaks driver | `apt-mark showhold` missing | Re-apply hold: `apt-mark hold nvidia-driver-560*` |

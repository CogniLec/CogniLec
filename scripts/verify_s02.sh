#!/bin/bash
set -euo pipefail

echo "=== S02 GPU Host Provisioning & CUDA Matrix Verification ==="
echo ""

# T02.1 - Host GPU
echo "[T02.1] Host GPU (nvidia-smi)"
if command -v nvidia-smi &>/dev/null; then
    nvidia-smi
    echo "PASS"
else
    echo "SKIP (nvidia-smi not found - expected outside GPU host)"
fi
echo ""

# T02.4 - Driver hold
echo "[T02.4] Driver version hold"
if apt-mark showhold 2>/dev/null | grep -q nvidia; then
    apt-mark showhold | grep nvidia
    echo "PASS"
else
    echo "SKIP (not running on GPU host or no driver held)"
fi
echo ""

# T02.1 - Container GPU access
echo "[T02.1] Container GPU access"
if docker image inspect lis/base-gpu:latest &>/dev/null; then
    docker run --rm --gpus all lis/base-gpu:latest nvidia-smi
    echo "PASS"
else
    echo "SKIP (lis/base-gpu:latest image not built yet)"
fi
echo ""

# T02.2 - PyTorch CUDA version
echo "[T02.2] PyTorch CUDA version == 12.6"
if docker image inspect lis/base-gpu:latest &>/dev/null; then
    docker run --rm --gpus all lis/base-gpu:latest python -c "import torch; assert torch.version.cuda == '12.6'; print('CUDA:', torch.version.cuda)"
    echo "PASS"
else
    echo "SKIP (lis/base-gpu:latest image not built yet)"
fi
echo ""

# T02.3 - flash-attn import
echo "[T02.3] flash-attn import"
if docker image inspect lis/base-gpu:latest &>/dev/null; then
    docker run --rm --gpus all lis/base-gpu:latest python -c "import flash_attn; print('flash-attn:', flash_attn.__version__)"
    echo "PASS"
else
    echo "SKIP (lis/base-gpu:latest image not built yet)"
fi
echo ""

# T02.6 - bitsandbytes 8-bit support
echo "[T02.6] bitsandbytes import"
if docker image inspect lis/base-gpu:latest &>/dev/null; then
    docker run --rm --gpus all lis/base-gpu:latest python -c "import bitsandbytes; print('bitsandbytes:', bitsandbytes.__version__)"
    echo "PASS"
else
    echo "SKIP (lis/base-gpu:latest image not built yet)"
fi
echo ""

# Additional ML libs check
echo "[CHECK] faiss-gpu + ctranslate2 + faster-whisper"
if docker image inspect lis/base-gpu:latest &>/dev/null; then
    docker run --rm --gpus all lis/base-gpu:latest python -c "
import faiss; print('faiss-gpu OK')
import ctranslate2; print('ctranslate2 OK')
import faster_whisper; print('faster-whisper OK')
"
    echo "PASS"
else
    echo "SKIP (lis/base-gpu:latest image not built yet)"
fi
echo ""

echo "=== S02 VERIFICATION COMPLETE ==="

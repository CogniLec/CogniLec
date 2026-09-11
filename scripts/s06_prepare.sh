#!/usr/bin/env bash
# S06 Prepare — Pull S04/S05 data via DVC and verify environment
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== S06: Preparing environment ==="

# Pull DVC data (S04 corpus + S05 ground truth)
if command -v dvc &>/dev/null; then
    echo "Pulling DVC data..."
    cd "$PROJECT_ROOT"
    dvc pull || echo "WARNING: DVC pull failed or not configured"
else
    echo "WARNING: DVC not installed — skipping data pull"
fi

# Verify required directories exist
for dir in data/corpus data/ground_truth; do
    if [ -d "$PROJECT_ROOT/$dir" ]; then
        echo "OK: $dir exists ($(find "$PROJECT_ROOT/$dir" -type f | wc -l) files)"
    else
        echo "MISSING: $dir — ensure S04/S05 outputs are present"
    fi
done

# Verify MLflow is reachable
if curl -sf http://mlflow:5000/health >/dev/null 2>&1; then
    echo "OK: MLflow is reachable at http://mlflow:5000"
elif curl -sf http://localhost:5000/health >/dev/null 2>&1; then
    echo "OK: MLflow is reachable at http://localhost:5000"
else
    echo "WARNING: MLflow unreachable — start with: docker compose up -d mlflow"
fi

# Check GPU availability
if command -v nvidia-smi &>/dev/null; then
    echo "GPU status:"
    nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader
else
    echo "WARNING: nvidia-smi not found — GPU not available"
fi

echo "=== S06: Preparation complete ==="

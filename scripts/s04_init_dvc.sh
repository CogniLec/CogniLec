#!/bin/bash
set -euo pipefail

# S04: Initialize DVC with MinIO remote
# Usage: ./s04_init_dvc.sh

echo "=== Initializing DVC for S04 Audio Corpus ==="

# Check if DVC is installed
if ! command -v dvc &> /dev/null; then
    echo "ERROR: DVC is not installed. Install with: pip install dvc[s3]"
    exit 1
fi

# Initialize DVC if not already initialized
if [ ! -d ".dvc" ]; then
    echo "Initializing DVC..."
    dvc init
fi

# Configure DVC remote
echo "Configuring DVC remote (origin) pointing to MinIO lis-eval bucket..."
dvc remote add -d origin s3://lis-eval --force
dvc remote modify origin endpointurl http://localhost:9000
dvc remote modify origin access_key_id "${MINIO_ACCESS_KEY:-minioadmin}"
dvc remote modify origin secret_access_key "${MINIO_SECRET_KEY:-minioadmin}"
dvc remote modify origin region us-east-1

echo "DVC remote configured successfully:"
dvc remote -v

echo "=== DVC initialization complete ==="

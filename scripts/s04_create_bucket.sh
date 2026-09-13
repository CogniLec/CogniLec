#!/bin/bash
set -euo pipefail

# S04: Create MinIO lis-eval bucket if it doesn't exist
# Usage: ./s04_create_bucket.sh

echo "=== Creating MinIO lis-eval bucket ==="

# Check MinIO health
if ! curl -sf http://localhost:9000/minio/health/live > /dev/null 2>&1; then
    echo "ERROR: MinIO not reachable at localhost:9000"
    echo "Ensure MinIO is running: docker compose up -d minio"
    exit 1
fi

# Configure mc alias if needed
if ! mc alias list local >/dev/null 2>&1; then
    echo "Configuring MinIO client alias..."
    mc alias set local http://localhost:9000 \
        "${MINIO_ACCESS_KEY:-minioadmin}" \
        "${MINIO_SECRET_KEY:-minioadmin}" \
        --api S3v4
fi

# Create bucket if it doesn't exist
if mc ls local/lis-eval >/dev/null 2>&1; then
    echo "Bucket 'lis-eval' already exists"
else
    echo "Creating bucket 'lis-eval'..."
    mc mb local/lis-eval
    echo "Bucket 'lis-eval' created"
fi

# Verify bucket
echo "Bucket contents:"
mc ls local/lis-eval/ 2>/dev/null || echo "  (empty)"
echo "=== Bucket ready ==="

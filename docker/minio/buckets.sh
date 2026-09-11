#!/bin/bash
# MinIO Bucket Initialization Script
# Runs on container startup via docker-entrypoint-initdb.d/

set -e

# Wait for MinIO to be ready
until curl -sf http://localhost:9000/minio/health/live; do
    echo "Waiting for MinIO..."
    sleep 2
done

# Configure mc client
mc alias set local http://localhost:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}" --api S3v4

# Create buckets with policies
buckets=(
    "lis-audio"
    "lis-uploads"
    "lis-generated"
    "lis-exports"
    "lis-eval"
)

for bucket in "${buckets[@]}"; do
    if ! mc ls local/"${bucket}" >/dev/null 2>&1; then
        echo "Creating bucket: ${bucket}"
        mc mb local/"${bucket}" --ignore-existing
    else
        echo "Bucket exists: ${bucket}"
    fi
done

# Set bucket policies
# lis-audio: ILM 30-day purge after session complete (enforced via lifecycle)
mc ilm rule add local/lis-audio --expire-days 30 --filter "prefix=audio/" 2>/dev/null || true

# lis-exports: ILM 7-day purge
mc ilm rule add local/lis-exports --expire-days 7 2>/dev/null || true

# lis-uploads: No ILM (permanent until manually cleaned)
# lis-generated: No ILM (permanent)
# lis-eval: No ILM (permanent, versioned with DVC)

# Enable versioning for eval bucket
mc version enable local/lis-eval 2>/dev/null || true

# Public read for exports (if needed for sharing)
# mc anonymous set download local/lis-exports 2>/dev/null || true

echo "MinIO buckets initialized successfully"

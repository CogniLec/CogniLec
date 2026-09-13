#!/bin/bash
# MinIO Bucket Initialization Script
# Run from an init container after MinIO is healthy.
# Usage: docker compose run --rm minio-init

set -e

MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://minio:9000}"

# Read credentials from secrets files (Docker secrets _FILE pattern)
if [ -f "${MINIO_ROOT_USER_FILE:-}" ]; then
    MINIO_ROOT_USER="$(cat "${MINIO_ROOT_USER_FILE}")"
fi
if [ -f "${MINIO_ROOT_PASSWORD_FILE:-}" ]; then
    MINIO_ROOT_PASSWORD="$(cat "${MINIO_ROOT_PASSWORD_FILE}")"
fi

# Fallback to env vars
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin}"

# Wait for MinIO to be ready
echo "Waiting for MinIO at ${MINIO_ENDPOINT}..."
until curl -sf "${MINIO_ENDPOINT}/minio/health/live" >/dev/null 2>&1; do
    sleep 2
done
echo "MinIO is ready."

# Configure mc client
mc alias set local "${MINIO_ENDPOINT}" "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}" --api S3v4

# Create buckets
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

# ILM: lis-audio — 30-day expiry on objects under audio/ prefix
mc ilm rule add local/lis-audio --expire-days 30 --prefix "audio/" 2>/dev/null || true

# ILM: lis-exports — 7-day expiry
mc ilm rule add local/lis-exports --expire-days 7 2>/dev/null || true

# Enable versioning for eval bucket
mc version enable local/lis-eval 2>/dev/null || true

echo "MinIO buckets initialized successfully"

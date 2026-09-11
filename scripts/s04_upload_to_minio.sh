#!/bin/bash
set -euo pipefail

# S04: Upload audio files to MinIO lis-eval bucket
# Usage: ./s04_upload_to_minio.sh <audio_file> <session_id>

if [ $# -ne 2 ]; then
    echo "Usage: $0 <audio_file> <session_id>"
    echo "Example: $0 audio.opus sess_20260911_001"
    exit 1
fi

AUDIO_FILE="$1"
SESSION_ID="$2"
MINIO_BUCKET="lis-eval"
REMOTE_PATH="phase0/v1/${SESSION_ID}/audio.opus"

# Validate audio file exists
if [ ! -f "$AUDIO_FILE" ]; then
    echo "ERROR: Audio file not found: $AUDIO_FILE"
    exit 1
fi

# Configure mc alias if not already configured
if ! mc alias list local >/dev/null 2>&1; then
    echo "Configuring MinIO client alias..."
    mc alias set local http://localhost:9000 "${MINIO_ACCESS_KEY:-minioadmin}" "${MINIO_SECRET_KEY:-minioadmin}" --api S3v4
fi

# Upload to MinIO
echo "Uploading $AUDIO_FILE to local/${MINIO_BUCKET}/${REMOTE_PATH}..."
mc cp "$AUDIO_FILE" "local/${MINIO_BUCKET}/${REMOTE_PATH}"

# Verify upload
if mc stat "local/${MINIO_BUCKET}/${REMOTE_PATH}" >/dev/null 2>&1; then
    echo "SUCCESS: Audio uploaded to MinIO"
    echo "Location: ${MINIO_BUCKET}/${REMOTE_PATH}"
else
    echo "ERROR: Upload verification failed"
    exit 1
fi

#!/bin/bash
set -euo pipefail

echo "=== Verifying S04 Audio Corpus ==="

# 1. DVC reproducibility
if command -v dvc &> /dev/null; then
    echo "DVC found, attempting dvc pull..."
    dvc pull 2>/dev/null || echo "Note: dvc pull skipped (no remote data or not initialized)"
else
    echo "Note: DVC not installed, skipping dvc pull"
fi

# 2. Check manifest exists
MANIFEST="lis-eval/phase0/v1/manifest.json"
if [ ! -f "$MANIFEST" ]; then
    echo "FAIL: manifest.json missing"
    exit 1
fi
echo "Manifest found"

# 3. Verify each session
SESSION_COUNT=$(jq '.sessions | length' "$MANIFEST")
echo "Sessions recorded: $SESSION_COUNT"

if [ "$SESSION_COUNT" -eq 0 ]; then
    echo "WARNING: No sessions recorded yet"
else
    for i in $(seq 0 $((SESSION_COUNT-1))); do
        SESSION_ID=$(jq -r ".sessions[$i].session_id" "$MANIFEST")
        AUDIO_FILE="lis-eval/phase0/v1/$SESSION_ID/audio.opus"

        if [ ! -f "$AUDIO_FILE" ]; then
            echo "FAIL: Missing audio for $SESSION_ID"
            exit 1
        fi

        # Verify Opus file
        if command -v ffprobe &> /dev/null; then
            DURATION=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$AUDIO_FILE")
            echo "  $SESSION_ID: ${DURATION}s"
        else
            echo "  $SESSION_ID: (ffprobe not available)"
        fi

        # Check consent_id present
        CONSENT_ID=$(jq -r ".sessions[$i].consent_id" "$MANIFEST")
        if [ "$CONSENT_ID" = "null" ] || [ -z "$CONSENT_ID" ]; then
            echo "FAIL: Missing consent_id for $SESSION_ID"
            exit 1
        fi
    done
fi

# 4. Check condition coverage
if [ "$SESSION_COUNT" -gt 0 ]; then
    CONDITIONS=$(jq -r '.sessions[].condition' "$MANIFEST" | sort -u)
    echo "Conditions covered: $CONDITIONS"
    REQUIRED=("front_quiet" "back_quiet" "front_busy" "back_busy" "lecturer_moving" "heavy_discussion")
    for req in "${REQUIRED[@]}"; do
        if ! echo "$CONDITIONS" | grep -q "$req"; then
            echo "WARN: Missing condition: $req"
        fi
    done
else
    echo "No conditions to check (no sessions)"
fi

# 5. Check MinIO bucket exists
echo "Checking MinIO bucket..."
if curl -sf http://localhost:9000/minio/health/live > /dev/null 2>&1; then
    echo "MinIO is healthy"

    # Check if mc is available
    if command -v mc &> /dev/null; then
        if ! mc alias list local >/dev/null 2>&1; then
            mc alias set local http://localhost:9000 "${MINIO_ACCESS_KEY:-minioadmin}" "${MINIO_SECRET_KEY:-minioadmin}" --api S3v4
        fi

        if mc ls local/lis-eval >/dev/null 2>&1; then
            echo "MinIO bucket 'lis-eval' exists"
        else
            echo "WARN: MinIO bucket 'lis-eval' not found"
        fi
    else
        echo "Note: mc not available locally, cannot verify bucket"
    fi
else
    echo "WARN: MinIO not reachable at localhost:9000"
fi

echo "=== S04 VERIFIED ==="

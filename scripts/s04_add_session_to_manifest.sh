#!/bin/bash
set -euo pipefail

# S04: Add a session entry to the manifest.json
# Usage: ./s04_add_session_to_manifest.sh <session_id> [room] [device] [position] [condition] [subject] [consent_id]
#
# Conditions (must cover all from spec):
#   front_quiet, back_quiet, front_busy, back_busy, lecturer_moving, heavy_discussion

if [ $# -lt 1 ]; then
    echo "Usage: $0 <session_id> [room] [device] [position] [condition] [subject] [consent_id]"
    echo ""
    echo "Example:"
    echo "  $0 sess_20260911_001 'Room 101' 'iPhone 15' 'front_row' 'front_quiet' 'CS101' 'consent_001'"
    echo ""
    echo "Conditions: front_quiet, back_quiet, front_busy, back_busy, lecturer_moving, heavy_discussion"
    exit 1
fi

SESSION_ID="$1"
ROOM="${2:-TBD}"
DEVICE="${3:-TBD}"
POSITION="${4:-front_row}"
CONDITION="${5:-front_quiet}"
SUBJECT="${6:-TBD}"
CONSENT_ID="${7:-TBD}"

MANIFEST="lis-eval/phase0/v1/manifest.json"
AUDIO_FILE="lis-eval/phase0/v1/${SESSION_ID}/audio.opus"

# Check manifest exists
if [ ! -f "$MANIFEST" ]; then
    echo "ERROR: Manifest not found at $MANIFEST"
    exit 1
fi

# Check audio file exists
if [ ! -f "$AUDIO_FILE" ]; then
    echo "WARNING: Audio file not found at $AUDIO_FILE"
    echo "Make sure to convert and place audio before adding to manifest"
fi

# Get audio metadata if available
AUDIO_SIZE=0
AUDIO_DURATION=0
SAMPLE_RATE=48000
CHANNELS=1
CODEC="opus"

if [ -f "$AUDIO_FILE" ] && command -v ffprobe &> /dev/null; then
    AUDIO_SIZE=$(stat -c%s "$AUDIO_FILE" 2>/dev/null || stat -f%z "$AUDIO_FILE" 2>/dev/null || echo 0)
    AUDIO_DURATION=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$AUDIO_FILE" 2>/dev/null || echo 0)
    AUDIO_DURATION=$(printf "%.0f" "$AUDIO_DURATION" 2>/dev/null || echo 0)
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Create new session entry
NEW_ENTRY=$(cat <<EOF
{
  "session_id": "${SESSION_ID}",
  "timestamp": "${TIMESTAMP}",
  "room": "${ROOM}",
  "device": "${DEVICE}",
  "position": "${POSITION}",
  "duration_seconds": ${AUDIO_DURATION},
  "subject": "${SUBJECT}",
  "condition": "${CONDITION}",
  "consent_id": "${CONSENT_ID}",
  "audio_file": "${SESSION_ID}/audio.opus",
  "audio_size_bytes": ${AUDIO_SIZE},
  "audio_duration_seconds": ${AUDIO_DURATION},
  "audio_sample_rate": ${SAMPLE_RATE},
  "audio_channels": ${CHANNELS},
  "audio_codec": "${CODEC}"
}
EOF
)

# Check if session already exists
EXISTING=$(jq --arg sid "$SESSION_ID" '.sessions[] | select(.session_id == $sid)' "$MANIFEST" 2>/dev/null)
if [ -n "$EXISTING" ]; then
    echo "ERROR: Session $SESSION_ID already exists in manifest"
    exit 1
fi

# Add to manifest
TMPFILE=$(mktemp)
jq --argjson entry "$NEW_ENTRY" '.sessions += [$entry]' "$MANIFEST" > "$TMPFILE" && mv "$TMPFILE" "$MANIFEST"

echo "Added session $SESSION_ID to manifest"
echo "  Room: $ROOM"
echo "  Device: $DEVICE"
echo "  Position: $POSITION"
echo "  Condition: $CONDITION"
echo "  Subject: $SUBJECT"
echo "  Consent: $CONSENT_ID"

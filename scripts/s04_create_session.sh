#!/bin/bash
set -euo pipefail

# S04: Create a new session directory with proper structure
# Usage: ./s04_create_session.sh <session_id>
# Example: ./s04_create_session.sh sess_20260911_001

if [ $# -ne 1 ]; then
    echo "Usage: $0 <session_id>"
    echo "Example: $0 sess_20260911_001"
    exit 1
fi

SESSION_ID="$1"
SESSION_DIR="lis-eval/phase0/v1/${SESSION_ID}"

if [ -d "$SESSION_DIR" ]; then
    echo "WARNING: Session directory already exists: $SESSION_DIR"
    exit 1
fi

mkdir -p "$SESSION_DIR"
echo "Created session directory: $SESSION_DIR"
echo ""
echo "Next steps:"
echo "  1. Record audio and save to: ${SESSION_DIR}/recording.wav"
echo "  2. Run: ./scripts/s04_convert_to_opus.sh ${SESSION_DIR}/recording.wav ${SESSION_DIR}"
echo "  3. Run: ./scripts/s04_add_session_to_manifest.sh ${SESSION_ID}"

#!/bin/bash
set -euo pipefail

# S04: List all sessions in the manifest with their conditions
# Usage: ./s04_list_sessions.sh

MANIFEST="lis-eval/phase0/v1/manifest.json"

if [ ! -f "$MANIFEST" ]; then
    echo "ERROR: Manifest not found at $MANIFEST"
    exit 1
fi

SESSION_COUNT=$(jq '.sessions | length' "$MANIFEST")
echo "=== S04 Audio Corpus Sessions ==="
echo "Total sessions: $SESSION_COUNT"
echo ""

if [ "$SESSION_COUNT" -eq 0 ]; then
    echo "No sessions recorded yet."
    exit 0
fi

# Print table header
printf "%-25s %-15s %-20s %-20s %-20s\n" "SESSION_ID" "CONDITION" "ROOM" "DEVICE" "SUBJECT"
printf "%-25s %-15s %-20s %-20s %-20s\n" "---------" "---------" "----" "------" "-------"

for i in $(seq 0 $((SESSION_COUNT-1))); do
    SESSION_ID=$(jq -r ".sessions[$i].session_id" "$MANIFEST")
    CONDITION=$(jq -r ".sessions[$i].condition" "$MANIFEST")
    ROOM=$(jq -r ".sessions[$i].room" "$MANIFEST")
    DEVICE=$(jq -r ".sessions[$i].device" "$MANIFEST")
    SUBJECT=$(jq -r ".sessions[$i].subject" "$MANIFEST")
    printf "%-25s %-15s %-20s %-20s %-20s\n" "$SESSION_ID" "$CONDITION" "$ROOM" "$DEVICE" "$SUBJECT"
done

echo ""

# Check condition coverage
echo "=== Condition Coverage ==="
CONDITIONS=$(jq -r '.sessions[].condition' "$MANIFEST" | sort -u)
REQUIRED=("front_quiet" "back_quiet" "front_busy" "back_busy" "lecturer_moving" "heavy_discussion")

for req in "${REQUIRED[@]}"; do
    if echo "$CONDITIONS" | grep -q "^${req}$"; then
        COUNT=$(jq --arg c "$req" '[.sessions[] | select(.condition == $c)] | length' "$MANIFEST")
        echo "  [OK] $req ($COUNT sessions)"
    else
        echo "  [MISSING] $req"
    fi
done

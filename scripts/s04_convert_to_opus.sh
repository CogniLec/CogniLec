#!/bin/bash
set -euo pipefail

# S04: Convert audio file to Opus format per spec
# Usage: ./s04_convert_to_opus.sh <input_file> <output_dir>
# Example: ./s04_convert_to_opus.sh recording.wav lis-eval/phase0/v1/sess_20260911_001

if [ $# -lt 2 ]; then
    echo "Usage: $0 <input_file> <output_dir>"
    echo "Example: $0 recording.wav lis-eval/phase0/v1/sess_20260911_001"
    echo ""
    echo "Converts input audio to Opus format: 48kHz, mono, ~24kbps"
    exit 1
fi

INPUT_FILE="$1"
OUTPUT_DIR="$2"
OUTPUT_FILE="${OUTPUT_DIR}/audio.opus"

# Validate input exists
if [ ! -f "$INPUT_FILE" ]; then
    echo "ERROR: Input file not found: $INPUT_FILE"
    exit 1
fi

# Check ffmpeg is available
if ! command -v ffmpeg &> /dev/null; then
    echo "ERROR: ffmpeg is not installed"
    exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Convert to Opus per spec: 48kHz, mono, ~24kbps
echo "Converting $INPUT_FILE to Opus (48kHz, mono, 24kbps)..."
ffmpeg -y -i "$INPUT_FILE" \
    -c:a libopus \
    -b:a 24k \
    -ac 1 \
    -ar 48000 \
    "$OUTPUT_FILE"

# Verify output
if [ ! -f "$OUTPUT_FILE" ]; then
    echo "ERROR: Conversion failed, output not created"
    exit 1
fi

# Report file size (spec target: ~15MB for 60min)
FILE_SIZE=$(stat -c%s "$OUTPUT_FILE" 2>/dev/null || stat -f%z "$OUTPUT_FILE" 2>/dev/null)
FILE_SIZE_MB=$(echo "scale=2; $FILE_SIZE / 1048576" | bc)

if command -v ffprobe &> /dev/null; then
    DURATION=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$OUTPUT_FILE")
    echo "Conversion complete:"
    echo "  File: $OUTPUT_FILE"
    echo "  Duration: ${DURATION}s"
    echo "  Size: ${FILE_SIZE_MB}MB"
else
    echo "Conversion complete: $OUTPUT_FILE (${FILE_SIZE_MB}MB)"
fi

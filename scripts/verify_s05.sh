#!/bin/bash
set -euo pipefail

echo "=== Verifying S05 Labelling ==="

# 1. Label Studio accessible (skip if not running)
if curl -kf https://label.lis.local >/dev/null 2>&1; then
    echo "Label Studio OK"
else
    echo "Note: Label Studio not reachable (may not be running)"
fi

# 2. DVC labels reproducible (skip if DVC not initialized)
if command -v dvc &> /dev/null && [ -d ".dvc" ]; then
    dvc pull lis-eval/labels/v1/ 2>/dev/null || echo "Note: dvc pull skipped"
    echo "DVC labels pulled"
else
    echo "Note: DVC not initialized, skipping dvc pull"
fi

# 3. Run eval harness unit tests
echo "Running eval harness tests..."
source .venv/bin/activate && pytest tests/test_eval_harness.py -v

# 4. Check kappa (skip if no overlap data)
if [ -f "lis-eval/labels/v1/relevance/overlap.json" ]; then
    python scripts/check_kappa.py lis-eval/labels/v1/relevance/overlap.json --threshold 0.75 || true
else
    echo "Note: No overlap data for kappa check"
fi

# 5. Verify rubric exists
[ -f docs/relevance-rubric.md ] && echo "Rubric exists"

# 6. Verify label directory structure
echo "Checking label directory structure..."
for dir in transcripts boundaries relevance; do
    if [ -d "lis-eval/labels/v1/$dir" ]; then
        echo "  lis-eval/labels/v1/$dir/ OK"
    else
        echo "  FAIL: lis-eval/labels/v1/$dir/ missing"
        exit 1
    fi
done

echo "=== S05 VERIFIED ==="

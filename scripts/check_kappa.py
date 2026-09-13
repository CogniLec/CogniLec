#!/usr/bin/env python3
"""S05 — Inter-annotator agreement checker (Cohen's kappa).

Reads overlap labels and computes pairwise Cohen's kappa for every
annotator pair. Two input shapes are supported:

  - JSON (long or wide): a list of records, either
    {"utterance_id": ..., "annotator": ..., "label": ...}  (long)
    or {"utterance_id": ..., "annotator1": ..., "annotator2": ..., ...}  (wide,
    one column per annotator, as produced by the label export in
    lis-eval/labels/v1/relevance/overlap.json)
  - CSV with columns [utterance_id, annotator, label] (long form)

Usage:
    python scripts/check_kappa.py lis-eval/labels/v1/relevance/overlap.json
    python scripts/check_kappa.py data/labels/overlap.csv --threshold 0.75
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from sklearn.metrics import cohen_kappa_score


def _rows_to_wide(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Normalise a list of row-dicts (long or wide) → {utterance_id: {annotator: label}}."""
    data: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        uid = row["utterance_id"]
        if "annotator" in row and "label" in row:
            # Long form: one row per (utterance, annotator).
            data[uid][row["annotator"]] = row["label"]
        else:
            # Wide form: one column per annotator (e.g. annotator1, annotator2).
            for key, value in row.items():
                if key == "utterance_id":
                    continue
                data[uid][key] = value
    return dict(data)


def load_labels(path: str) -> dict[str, dict[str, str]]:
    """Load a JSON or CSV overlap-labels file → {utterance_id: {annotator: label}}."""
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        with open(path) as f:
            rows = json.load(f)
        return _rows_to_wide(rows)
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return _rows_to_wide(rows)


def compute_pairwise_kappa(
    data: dict[str, dict[str, str]],
) -> dict[tuple[str, str], float]:
    """Compute Cohen's kappa for every pair of annotators."""
    annotators: set[str] = set()
    for labels in data.values():
        annotators.update(labels.keys())
    annotators = sorted(annotators)

    results: dict[tuple[str, str], float] = {}
    for a1, a2 in combinations(annotators, 2):
        # Only utterances both annotators labelled
        shared = [uid for uid, labels in data.items() if a1 in labels and a2 in labels]
        if len(shared) < 2:
            results[(a1, a2)] = float("nan")
            continue
        refs = [data[uid][a1] for uid in shared]
        preds = [data[uid][a2] for uid in shared]
        kappa = cohen_kappa_score(refs, preds, labels=["on_topic", "off_topic"])
        results[(a1, a2)] = kappa
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Check inter-annotator agreement (Cohen's kappa)")
    parser.add_argument("csv_path", help="Path to overlap labels file (.json or .csv)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        help="Minimum acceptable kappa (default: 0.75)",
    )
    args = parser.parse_args()

    data = load_labels(args.csv_path)
    if not data:
        print("ERROR: No data loaded.", file=sys.stderr)
        return 1

    results = compute_pairwise_kappa(data)

    all_pass = True
    for (a1, a2), kappa in results.items():
        status = "PASS" if kappa >= args.threshold else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  {a1} vs {a2}: kappa={kappa:.4f}  [{status}]")

    n_annotators = len({a for labels in data.values() for a in labels})
    n_utterances = len(data)
    print(f"\nSummary: {n_annotators} annotators, {n_utterances} utterances")
    print(f"Threshold: kappa >= {args.threshold}")

    if all_pass:
        print("RESULT: ALL PAIRS PASS")
        return 0
    else:
        print("RESULT: SOME PAIRS BELOW THRESHOLD — review disagreements and refine rubric")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

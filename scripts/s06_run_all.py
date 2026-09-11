#!/usr/bin/env python3
"""S06 Run All — Orchestrates the full ASR & Embedding bake-off pipeline."""

import logging
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent


def run_step(name: str, script: str) -> bool:
    """Run a bake-off step and report success/failure."""
    log.info("=" * 60)
    log.info("STEP: %s", name)
    log.info("=" * 60)

    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / script)],
            cwd=str(SCRIPT_DIR.parent),
            capture_output=False,
            timeout=14400,  # 4 hour max per step
        )
        elapsed = time.time() - t0
        if result.returncode != 0:
            log.error("STEP FAILED: %s (exit code %d)", name, result.returncode)
            return False
        log.info("STEP COMPLETE: %s (%.1fs)", name, elapsed)
        return True
    except subprocess.TimeoutExpired:
        log.error("STEP TIMEOUT: %s (>4h)", name)
        return False
    except Exception as e:
        log.error("STEP ERROR: %s — %s", name, e)
        return False


def main():
    log.info("=" * 60)
    log.info("S06: ASR & Embedding Bake-Off — Full Pipeline")
    log.info("=" * 60)

    steps = [
        ("ASR Bake-Off", "s06_asr_bakeoff.py"),
        ("Embedding Bake-Off", "s06_embedding_bakeoff.py"),
        ("Disagreement Analysis", "s06_disagreement.py"),
        ("Generate Reports", "s06_report.py"),
        ("Gate Check", "s06_check_gates.py"),
    ]

    t0 = time.time()
    results: list[tuple[str, bool]] = []

    for name, script in steps:
        ok = run_step(name, script)
        results.append((name, ok))
        if not ok and "Bake-Off" in name:
            # Continue to report what we have, but flag failure
            log.warning("Bake-off step failed — continuing to generate partial reports")

    elapsed = time.time() - t0

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info("PIPELINE SUMMARY (%.1fs total)", elapsed)
    log.info("=" * 60)

    all_pass = True
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        log.info("  [%s] %s", status, name)
        all_pass &= ok

    if all_pass:
        log.info("ALL STEPS PASSED — S06 COMPLETE")
    else:
        log.warning("ONE OR MORE STEPS FAILED — review logs above")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())

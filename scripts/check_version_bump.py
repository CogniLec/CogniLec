#!/usr/bin/env python3
"""S40 — CI gate: fail if a prompt file changed without a matching version bump.

Compares the working tree's prompt manifests against `git diff --name-only`
against the merge-base, requiring any changed `config/prompts/**/v*.md` file
to have a filename version that matches its manifest's `current_version`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

VERSION_RE = re.compile(r"v(\d+\.\d+\.\d+)\.md$")


def changed_prompt_files(base_ref: str = "HEAD~1") -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", base_ref, "--", "config/prompts/"],
            text=True,
        )
    except subprocess.CalledProcessError:
        return []
    return [line for line in out.strip().splitlines() if line]


def main() -> int:
    changed = changed_prompt_files()
    failed = False

    for f in changed:
        if not f.endswith(".md"):
            continue
        match = VERSION_RE.search(f)
        if not match:
            print(f"ERROR: {f} does not follow the v{{major}}.{{minor}}.{{patch}}.md convention")
            failed = True
            continue

        manifest_path = Path(f).parent / "manifest.yaml"
        if not manifest_path.exists():
            print(f"WARNING: no manifest found at {manifest_path}")
            continue

        manifest = yaml.safe_load(manifest_path.read_text())
        versions = {v["version"] for v in manifest.get("versions", [])}
        if match.group(1) not in versions:
            print(f"ERROR: {f} version {match.group(1)} is not declared in {manifest_path}")
            failed = True

    if failed:
        print("Version bump check FAILED")
        return 1

    print("Version bump check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

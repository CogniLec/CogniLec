#!/usr/bin/env python3
"""S38 — CI gate: fail if any agent A1-A6 lacks a registered output schema."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.llm.schema_registry import SchemaRegistry


def main() -> int:
    try:
        registry = SchemaRegistry()
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"schema registry OK — {len(registry.list_schemas())} agents registered")
    return 0


if __name__ == "__main__":
    sys.exit(main())

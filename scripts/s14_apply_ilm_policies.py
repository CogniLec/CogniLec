#!/usr/bin/env python3
"""S14: Apply ILM (lifecycle) policies to MinIO buckets, idempotently.

- lis-audio:     30-day expiration (post-complete cleanup)
- lis-exports:   7-day expiration
- lis-uploads / lis-generated / lis-eval: no ILM (permanent; lis-eval is
  versioned via DVC and must never receive a lifecycle rule)

Usage:
    .venv/bin/python scripts/s14_apply_ilm_policies.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.storage.client import StorageClient
from src.services.storage.models import BucketName


def main() -> None:
    client = StorageClient()
    client.apply_lifecycle_policies()

    audio_rules = client.get_lifecycle_rules(BucketName.AUDIO)
    exports_rules = client.get_lifecycle_rules(BucketName.EXPORTS)

    print(f"lis-audio ILM rules:   {audio_rules}")
    print(f"lis-exports ILM rules: {exports_rules}")
    print("ILM policies applied.")


if __name__ == "__main__":
    main()

"""S59 — pHash near-duplicate detection (T59.3, FR-4.19)."""

from __future__ import annotations

import io

import imagehash
from PIL import Image
from src.services.uploads.models import DEFAULT_PHASH_HAMMING_THRESHOLD


def compute_phash(image_bytes: bytes) -> str:
    with Image.open(io.BytesIO(image_bytes)) as img:
        return str(imagehash.phash(img))


def hamming_distance(hash_a: str, hash_b: str) -> int:
    return imagehash.hex_to_hash(hash_a) - imagehash.hex_to_hash(hash_b)


def find_duplicate(
    new_hash: str,
    existing: list[tuple[str, str]],
    threshold: int = DEFAULT_PHASH_HAMMING_THRESHOLD,
) -> str | None:
    """Return the asset id of the closest existing hash within `threshold`, if any.

    `existing` is a list of (asset_id, phash) pairs. Ties resolve to the
    smallest hamming distance found first in iteration order.
    """
    best_id: str | None = None
    best_distance = threshold + 1
    for asset_id, existing_hash in existing:
        distance = hamming_distance(new_hash, existing_hash)
        if distance <= threshold and distance < best_distance:
            best_id = asset_id
            best_distance = distance
    return best_id

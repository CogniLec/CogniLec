"""S63 — FLUX.1-schnell text-to-image generation service.

No `diffusers`/GPU-loaded FLUX weights exist in this sandbox (gap #2), so
`FLUXGenerator.generate` delegates to an injectable `backend` callable.
That callable's signature is `(concept_description: str) -> bytes` —
there is no parameter slot anywhere in this file, the schema
(`schema.py`), or the backend protocol through which an image could be
threaded in, which is what T63.2 traces end to end.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

GenerationBackend = Callable[[str], Awaitable[bytes]]


class FLUXGenerator:
    """Generates image bytes from a text concept description only.

    FR-4.9: `generate` accepts exactly one argument, the concept text.
    There is no `image`, `image_url`, `reference_image`, or `input_bytes`
    parameter, so a candidate image from S62 retrieval cannot be threaded
    through this call even by a caller that tried to.
    """

    def __init__(self, backend: GenerationBackend) -> None:
        self._backend = backend

    async def generate(self, concept_description: str) -> bytes:
        return await self._backend(concept_description)

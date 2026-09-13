"""S60 — common OCR provider interface (PaddleOCR / VLM-OCR / dots.ocr).

No real PaddleOCR/VLM/dots.ocr backend can be loaded in this sandbox (gap
#2: no GPU-loaded models; gap #9: no OCR binaries) so `PaddleOCRProvider`
and `VLMOCRProvider` below wrap an injectable transport, exactly like
`RerankerClient` (S54) and the LLM router (S37) do for the same reason —
the confidence/disagreement logic that consumes their output is real and
fully tested against fake providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

OCRTransport = Callable[[bytes], Awaitable[tuple[str, float]]]


class OCRProvider(ABC):
    @abstractmethod
    async def run(self, image_bytes: bytes) -> tuple[str, float]:
        """Run OCR on image bytes, return (text, confidence)."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider's backend is reachable/loaded."""


class TransportOCRProvider(OCRProvider):
    """Provider backed by an injectable async transport function."""

    def __init__(self, transport: OCRTransport | None, name: str) -> None:
        self._transport = transport
        self._name = name

    def is_available(self) -> bool:
        return self._transport is not None

    async def run(self, image_bytes: bytes) -> tuple[str, float]:
        if self._transport is None:
            msg = f"{self._name} backend not available in this environment"
            raise RuntimeError(msg)
        return await self._transport(image_bytes)
